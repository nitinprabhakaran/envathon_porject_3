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
        # For now, assume SonarQube key matches GitLab project name
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
    """Map SonarQube project key to GitLab project ID"""
    # In production, implement proper mapping logic
    # For demo, return a mock ID
    return "123"  # Replace with actual lookup