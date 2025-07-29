"""Webhook handlers for GitLab and SonarQube"""
from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any, List, Optional
import json
import uuid
import asyncio
from datetime import datetime
from utils.logger import log
from db.session_manager import SessionManager
from agents.pipeline_agent import PipelineAgent
from agents.quality_agent import QualityAgent

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Initialize components
session_manager = SessionManager()
pipeline_agent = PipelineAgent()
quality_agent = QualityAgent()

@router.post("/gitlab")
async def handle_gitlab_webhook(request: Request):
    """Handle GitLab pipeline failure webhook"""
    try:
        data = await request.json()
        log.info(f"Received GitLab webhook: {data.get('object_kind')}")
        
        # Validate webhook
        if data.get("object_kind") != "pipeline":
            return {"status": "ignored", "reason": "Not a pipeline event"}
        
        if data.get("object_attributes", {}).get("status") != "failed":
            return {"status": "ignored", "reason": "Not a failure event"}
        
        # Check if this is a SonarQube quality gate failure
        failed_jobs = [job for job in data.get("builds", []) if job.get("status") == "failed"]
        if failed_jobs:
            # Check if the only failed job is sonarqube-check
            sonar_jobs = [job for job in failed_jobs if "sonar" in job.get("name", "").lower()]
            if len(failed_jobs) == len(sonar_jobs) and len(sonar_jobs) > 0:
                log.info("Pipeline failed due to SonarQube quality gate - ignoring GitLab webhook")
                return {
                    "status": "ignored", 
                    "reason": "SonarQube quality gate failure - will be handled by SonarQube webhook"
                }

        # Extract metadata
        project = data.get("project", {})
        pipeline = data.get("object_attributes", {})
        
        metadata = {
            "project_id": str(project.get("id")),
            "project_name": project.get("name"),
            "pipeline_id": str(pipeline.get("id")),
            "pipeline_url": pipeline.get("url"),
            "branch": pipeline.get("ref"),
            "commit_sha": pipeline.get("sha"),
            "webhook_data": data
        }
        
        # Extract failed job info
        failed_jobs = [job for job in data.get("builds", []) if job.get("status") == "failed"]
        if failed_jobs:
            first_failed = failed_jobs[0]
            metadata["job_name"] = first_failed.get("name")
            metadata["failed_stage"] = first_failed.get("stage")
        
        # Create session
        session_id = str(uuid.uuid4())
        session = await session_manager.create_session(
            session_id=session_id,
            session_type="pipeline",
            project_id=metadata["project_id"],
            metadata=metadata
        )
        
        # Add initial message
        await session_manager.add_message(
            session_id,
            "system",
            f"Pipeline failure detected for {metadata['project_name']} - Pipeline #{metadata['pipeline_id']}"
        )
        
        # Start analysis in background
        asyncio.create_task(analyze_pipeline_failure(
            session_id,
            metadata["project_id"],
            metadata["pipeline_id"],
            data
        ))
        
        log.info(f"Created pipeline session {session_id}")
        return {
            "status": "analyzing",
            "session_id": session_id,
            "message": "Pipeline analysis started"
        }
        
    except Exception as e:
        log.error(f"Webhook processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/sonarqube")
async def handle_sonarqube_webhook(request: Request):
    """Handle SonarQube quality gate webhook"""
    try:
        data = await request.json()
        log.info(f"Received SonarQube webhook for project {data.get('project', {}).get('key')}")
        
        # Validate webhook
        quality_gate = data.get("qualityGate", {})
        if quality_gate.get("status") != "ERROR":
            return {"status": "ignored", "reason": "Quality gate passed"}
        
        # Extract metadata
        project = data.get("project", {})
        
        # Map SonarQube project to GitLab
        # In production, you'd have a mapping table or naming convention
        # For demo, use the project key as-is
        gitlab_project_id = await get_gitlab_project_id(project.get("key"))
        
        if not gitlab_project_id:
            log.error(f"Could not map SonarQube project {project.get('key')} to GitLab")
            raise HTTPException(status_code=404, detail="GitLab project not found")
        
        metadata = {
            "sonarqube_key": project.get("key"),
            "project_name": project.get("name"),
            "quality_gate_status": quality_gate.get("status"),
            "branch": data.get("branch", {}).get("name", "main"),
            "webhook_data": data,
            "gitlab_project_id": gitlab_project_id
        }
        
        # Create session
        session_id = str(uuid.uuid4())
        session = await session_manager.create_session(
            session_id=session_id,
            session_type="quality",
            project_id=gitlab_project_id,
            metadata=metadata
        )
        
        # Add initial message
        await session_manager.add_message(
            session_id,
            "system",
            f"Quality gate failure detected for {metadata['project_name']}"
        )
        
        # Start analysis in background
        asyncio.create_task(analyze_quality_issues(
            session_id,
            project.get("key"),
            gitlab_project_id,
            data
        ))
        
        log.info(f"Created quality session {session_id}")
        return {
            "status": "analyzing",
            "session_id": session_id,
            "message": "Quality analysis started"
        }
        
    except Exception as e:
        log.error(f"Webhook processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

async def analyze_pipeline_failure(session_id: str, project_id: str, pipeline_id: str, webhook_data: Dict):
    """Background task to analyze pipeline failure"""
    try:
        log.info(f"Starting pipeline analysis for session {session_id}")
        
        # Run analysis
        analysis = await pipeline_agent.analyze_failure(
            session_id, project_id, pipeline_id, webhook_data
        )
        
        # Extract text if analysis is a complex object
        if isinstance(analysis, dict) and "content" in analysis:
            content = analysis["content"]
            if isinstance(content, list) and len(content) > 0:
                analysis = content[0].get("text", str(analysis))
        
        # Store analysis in conversation
        await session_manager.add_message(session_id, "assistant", analysis)
        
        log.info(f"Pipeline analysis complete for session {session_id}")
        
    except Exception as e:
        log.error(f"Pipeline analysis failed: {e}", exc_info=True)
        await session_manager.add_message(
            session_id,
            "assistant",
            f"Analysis failed: {str(e)}"
        )

async def analyze_quality_issues(session_id: str, project_key: str, gitlab_project_id: str, webhook_data: Dict):
    """Background task to analyze quality issues"""
    try:
        log.info(f"Starting quality analysis for session {session_id}")
        
        # First, fetch actual metrics from SonarQube
        from tools.sonarqube import get_project_issues, get_project_metrics
        
        # Get issue counts by type
        bugs = await get_project_issues(project_key, types="BUG", limit=500)
        vulnerabilities = await get_project_issues(project_key, types="VULNERABILITY", limit=500)
        code_smells = await get_project_issues(project_key, types="CODE_SMELL", limit=500)
        
        # Get project metrics
        metrics = await get_project_metrics(project_key)
        
        # Calculate counts
        total_issues = len(bugs) + len(vulnerabilities) + len(code_smells)
        critical_count = sum(1 for b in bugs if b.get("severity") in ["CRITICAL", "BLOCKER"])
        critical_count += sum(1 for v in vulnerabilities if v.get("severity") in ["CRITICAL", "BLOCKER"])
        major_count = sum(1 for b in bugs if b.get("severity") == "MAJOR")
        major_count += sum(1 for v in vulnerabilities if v.get("severity") == "MAJOR")
        
        # Update session with quality metrics
        await session_manager.update_quality_metrics(
            session_id,
            {
                "total_issues": total_issues,
                "bug_count": len(bugs),
                "vulnerability_count": len(vulnerabilities),
                "code_smell_count": len(code_smells),
                "critical_issues": critical_count,
                "major_issues": major_count,
                "coverage": metrics.get("coverage", "0"),
                "duplicated_lines_density": metrics.get("duplicated_lines_density", "0"),
                "reliability_rating": metrics.get("reliability_rating", "E"),
                "security_rating": metrics.get("security_rating", "E"),
                "maintainability_rating": metrics.get("maintainability_rating", "E")
            }
        )
        
        # Run analysis
        analysis = await quality_agent.analyze_quality_issues(
            session_id, project_key, gitlab_project_id, webhook_data
        )
        
        # Extract text if analysis is a complex object
        if isinstance(analysis, dict) and "content" in analysis:
            content = analysis["content"]
            if isinstance(content, list) and len(content) > 0:
                analysis = content[0].get("text", str(analysis))
        
        # Store analysis in conversation
        await session_manager.add_message(session_id, "assistant", analysis)
        
        log.info(f"Quality analysis complete for session {session_id}")
        
    except Exception as e:
        log.error(f"Quality analysis failed: {e}", exc_info=True)
        await session_manager.add_message(
            session_id,
            "assistant",
            f"Analysis failed: {str(e)}"
        )

async def get_gitlab_project_id(sonarqube_key: str) -> Optional[str]:
    """Map SonarQube project key to GitLab project ID
    
    Strategy:
    1. Try exact match with project path
    2. Try match with project name
    3. Search in group if key contains group prefix
    """
    from tools.gitlab import get_gitlab_client
    
    log.info(f"Looking up GitLab project for SonarQube key: {sonarqube_key}")
    
    async with await get_gitlab_client() as client:
        try:
            # Strategy 1: Direct lookup by path (most common case)
            # SonarQube keys often match GitLab project paths
            if "/" in sonarqube_key:
                # It's a full path like "group/project"
                encoded_path = sonarqube_key.replace("/", "%2F")
                try:
                    response = await client.get(f"/projects/{encoded_path}")
                    if response.status_code == 200:
                        project_id = str(response.json().get("id"))
                        log.info(f"Found project by path: {sonarqube_key} -> {project_id}")
                        return project_id
                except:
                    pass
            
            # Strategy 2: Search by name (if key is just project name)
            search_params = {"search": sonarqube_key, "simple": "true"}
            response = await client.get("/projects", params=search_params)
            
            if response.status_code == 200:
                projects = response.json()
                
                # Try exact name match first
                for project in projects:
                    if project.get("name") == sonarqube_key:
                        project_id = str(project.get("id"))
                        log.info(f"Found project by exact name match: {sonarqube_key} -> {project_id}")
                        return project_id
                
                # Try path_with_namespace match
                for project in projects:
                    if project.get("path_with_namespace", "").endswith(f"/{sonarqube_key}"):
                        project_id = str(project.get("id"))
                        log.info(f"Found project by path suffix: {sonarqube_key} -> {project_id}")
                        return project_id
                
                # If only one result, use it
                if len(projects) == 1:
                    project_id = str(projects[0].get("id"))
                    log.info(f"Found single project match: {sonarqube_key} -> {project_id}")
                    return project_id
            
            # Strategy 3: If key contains underscore, try without group prefix
            # e.g., "envathon_payment-service" -> "payment-service"
            if "_" in sonarqube_key:
                parts = sonarqube_key.split("_", 1)
                if len(parts) == 2:
                    group_name, project_name = parts
                    
                    # Search in specific group
                    group_response = await client.get(f"/groups", params={"search": group_name})
                    if group_response.status_code == 200:
                        groups = group_response.json()
                        for group in groups:
                            if group.get("name").lower() == group_name.lower():
                                group_id = group.get("id")
                                
                                # Get projects in this group
                                projects_response = await client.get(
                                    f"/groups/{group_id}/projects",
                                    params={"search": project_name}
                                )
                                if projects_response.status_code == 200:
                                    group_projects = projects_response.json()
                                    for project in group_projects:
                                        if project.get("name") == project_name:
                                            project_id = str(project.get("id"))
                                            log.info(f"Found project in group: {sonarqube_key} -> {project_id}")
                                            return project_id
            
            log.error(f"Could not find GitLab project for SonarQube key: {sonarqube_key}")
            return None
            
        except Exception as e:
            log.error(f"Error looking up GitLab project: {e}")
            return None