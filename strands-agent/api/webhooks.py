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

async def check_quality_gate_in_logs(webhook_data: Dict[str, Any]) -> bool:
    """Check if pipeline failure is due to quality gate by analyzing logs"""
    from tools.gitlab import get_job_logs
    
    failed_jobs = [job for job in webhook_data.get("builds", []) if job.get("status") == "failed"]
    
    if not failed_jobs:
        return False
    
    # Sort by finished_at to get the most recent failure
    failed_jobs.sort(key=lambda x: x.get("finished_at", ""), reverse=True)
    
    # Only check the MOST RECENT failed job
    most_recent_failed_job = failed_jobs[0]
    project_id = str(webhook_data.get("project", {}).get("id"))
    
    try:
        job_id = str(most_recent_failed_job.get("id"))
        job_name = most_recent_failed_job.get("name", "")
        
        log.info(f"Checking most recent failed job: {job_name} (ID: {job_id})")
        
        # If it's a sonar/quality job, assume it's a quality failure
        if any(keyword in job_name.lower() for keyword in ['sonar', 'quality']):
            log.info(f"Job {job_name} is a quality-related job, treating as quality gate failure")
            return True
        
        logs = await get_job_logs(job_id, project_id)
        
        # Look for quality gate failure indicators in logs
        quality_indicators = [
            "Quality Gate failure",
            "QUALITY GATE STATUS: FAILED",
            "Quality gate failed",
            "SonarQube analysis reported",
            "Quality gate status: ERROR",
            "failed because the quality gate",
            "Your code fails the quality gate",
            "SonarQube Quality Gate has failed"
        ]
        
        logs_lower = logs.lower()
        if any(indicator.lower() in logs_lower for indicator in quality_indicators):
            log.info(f"Found quality gate failure in most recent job {job_name} logs")
            return True
            
    except Exception as e:
        log.warning(f"Could not fetch logs for job {most_recent_failed_job.get('id')}: {e}")
    
    return False

@router.post("/gitlab")
async def handle_gitlab_webhook(request: Request):
    """Handle GitLab pipeline failure webhook"""
    try:
        data = await request.json()
        log.info(f"Received GitLab webhook: {data.get('object_kind')}")
        
        # Validate webhook
        if data.get("object_kind") != "pipeline":
            return {"status": "ignored", "reason": "Not a pipeline event"}
        
        pipeline_status = data.get("object_attributes", {}).get("status")
        project_id = str(data.get("project", {}).get("id"))
        ref = data.get("object_attributes", {}).get("ref")
        
        # Handle successful pipelines
        if pipeline_status == "success":
            return await handle_pipeline_success(project_id, ref)
        
        # Only process failures
        if pipeline_status != "failed":
            return {"status": "ignored", "reason": "Not a failure event"}
        
        # Check if this is a quality gate failure
        is_quality_failure = await check_quality_gate_in_logs(data)
        
        # Check for existing sessions and handle fix branch failures
        existing_sessions = await session_manager.get_active_sessions()
        
        # Determine session type based on failure type
        if is_quality_failure:
            session_type = "quality"
            fix_branch_prefix = "fix/sonarqube_"
        else:
            session_type = "pipeline"
            fix_branch_prefix = "fix/pipeline_"
        
        # Check if this is a fix branch failure for an existing session
        if ref and ref.startswith(fix_branch_prefix):
            for session in existing_sessions:
                if (session.get("session_type") == session_type and 
                    session.get("project_id") == project_id and
                    session.get("current_fix_branch") == ref and
                    session.get("status") == "active"):
                    
                    # Update fix attempt status
                    await update_fix_attempt_status(session['id'], ref, "failed", 
                                                  f"{session_type.capitalize()} still failing")
                    
                    # Add system message for user awareness
                    await session_manager.add_message(
                        session['id'],
                        "system",
                        f"Fix attempt on branch {ref} failed - {session_type} still not passing"
                    )
                    
                    #  Store fix attempt in webhook_data for UI
                    webhook_data = session.get("webhook_data", {})
                    fix_attempts = webhook_data.get("fix_attempts", [])
                    fix_attempts.append({
                        "branch": ref,
                        "mr_id": session.get("merge_request_id"),
                        "status": "failed",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    webhook_data["fix_attempts"] = fix_attempts
                    await session_manager.update_session_metadata(session['id'], {"webhook_data": webhook_data})

                    log.info(f"Updated failed fix attempt for {session_type} session {session['id']}")
                    return {
                        "status": "updated",
                        "session_id": session['id'],
                        "message": "Fix attempt failed, ready for next iteration"
                    }
        
        # Check for existing active session (non-fix branch)
        for session in existing_sessions:
            if (session.get("session_type") == session_type and 
                session.get("project_id") == project_id and
                session.get("status") == "active"):
                
                log.info(f"Found existing {session_type} session {session['id']} for project {project_id}")
                return {
                    "status": "ignored",
                    "reason": f"Active {session_type} session already exists",
                    "session_id": session['id']
                }
        
        # Create new session
        if is_quality_failure:
            return await create_quality_session(data)
        else:
            return await create_pipeline_session(data)
        
    except Exception as e:
        log.error(f"Webhook processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def handle_pipeline_success(project_id: str, ref: str):
    """Handle successful pipeline runs"""
    sessions = await session_manager.get_active_sessions()
    
    # Check if this is a fix branch that succeeded
    if ref and ref.startswith("fix/"):
        for session in sessions:
            if (session.get("project_id") == project_id and 
                session.get("current_fix_branch") == ref and
                session.get("status") == "active"):
                
                # Update fix attempt status
                await update_fix_attempt_status(session["id"], ref, "success")
                await session_manager.mark_session_resolved(session["id"])
                log.info(f"Marked session {session['id']} as resolved - fix branch succeeded")
                
    # Check if this is main/master branch after merge
    elif ref in ["main", "master"]:
        for session in sessions:
            if (session.get("project_id") == project_id and 
                session.get("merge_request_url") and
                session.get("status") == "active" and
                session.get("current_fix_branch")):
                
                await session_manager.mark_session_resolved(session["id"])
                log.info(f"Marked session {session['id']} as resolved - main branch succeeded after merge")
    
    return {"status": "processed", "action": "checked_for_resolution"}


async def update_fix_attempt_status(session_id: str, branch_name: str, status: str, error_details: str = None):
    """Update fix attempt status for a session"""
    fix_attempts = await session_manager.get_fix_attempts(session_id)
    for attempt in fix_attempts:
        if attempt["branch_name"] == branch_name and attempt["status"] == "pending":
            await session_manager.update_fix_attempt(
                session_id,
                attempt["attempt_number"],
                status,
                error_details=error_details
            )


async def create_quality_session(data: Dict[str, Any]):
    """Create a new quality analysis session"""
    project = data.get("project", {})
    pipeline = data.get("object_attributes", {})
    
    sonarqube_key = project.get("name")
    gitlab_project_id = str(project.get("id"))
    
    # Get failed job details
    failed_jobs = [job for job in data.get("builds", []) if job.get("status") == "failed"]
    failed_jobs.sort(key=lambda x: x.get("finished_at", ""), reverse=True)
    failed_job = failed_jobs[0] if failed_jobs else {}
    
    metadata = {
        "sonarqube_key": sonarqube_key,
        "project_name": project.get("name"),
        "quality_gate_status": "ERROR",
        "branch": pipeline.get("ref", "main"),
        "webhook_data": data,
        "gitlab_project_id": gitlab_project_id,
        "pipeline_id": str(pipeline.get("id")),
        "pipeline_url": pipeline.get("url"),
        "job_name": failed_job.get("name", "sonarqube-check"),
        "failed_stage": failed_job.get("stage", "scan")
    }
    
    session_id = str(uuid.uuid4())
    session = await session_manager.create_session(
        session_id=session_id,
        session_type="quality",
        project_id=gitlab_project_id,
        metadata=metadata
    )
    
    await session_manager.add_message(
        session_id,
        "system",
        f"Quality gate failure detected for {metadata['project_name']} in pipeline #{metadata['pipeline_id']}"
    )
    
    # Start analysis in background
    asyncio.create_task(analyze_quality_from_pipeline(
        session_id,
        sonarqube_key,
        gitlab_project_id,
        data
    ))
    
    log.info(f"Created quality session {session_id}")
    return {
        "status": "analyzing",
        "session_id": session_id,
        "session_type": "quality",
        "message": "Quality gate failure analysis started"
    }


async def create_pipeline_session(data: Dict[str, Any]):
    """Create a new pipeline failure session"""
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
        failed_jobs.sort(key=lambda x: x.get("finished_at", ""), reverse=True)
        first_failed = failed_jobs[0]
        metadata["job_name"] = first_failed.get("name")
        metadata["failed_stage"] = first_failed.get("stage")
        log.info(f"Most recent failed job: {metadata['job_name']} (ID: {first_failed.get('id')})")
    
    session_id = str(uuid.uuid4())
    session = await session_manager.create_session(
        session_id=session_id,
        session_type="pipeline",
        project_id=metadata["project_id"],
        metadata=metadata
    )
    
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
        "session_type": "pipeline",
        "message": "Pipeline analysis started"
    }

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
        gitlab_project_id = await get_gitlab_project_id(project.get("key"))
        
        if not gitlab_project_id:
            log.error(f"Could not map SonarQube project {project.get('key')} to GitLab")
            raise HTTPException(status_code=404, detail="GitLab project not found")
        
        # Check if there's already an active quality session for this project
        existing_sessions = await session_manager.get_active_sessions()
        for session in existing_sessions:
            if (session.get("session_type") == "quality" and 
                session.get("project_id") == gitlab_project_id and
                session.get("status") == "active"):
                log.info(f"Found existing quality session {session['id']} for project {gitlab_project_id}")
                return {
                    "status": "existing",
                    "session_id": session['id'],
                    "message": "Using existing quality session"
                }
        
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
        error_msg = str(e)
        # Handle EventLoopException which contains curly braces
        if "EventLoopException" in type(e).__name__:
            error_msg = error_msg.replace("{", "{{").replace("}", "}}")
        
        log.error(f"Pipeline/Quality analysis failed: {error_msg}", exc_info=True)
        
        # Check if it's a token limit error
        if "prompt is too long" in error_msg:
            await session_manager.add_message(
                session_id,
                "assistant",
                "Analysis failed: The pipeline logs are too large to analyze. This typically happens with verbose test output or coverage reports. Please check the GitLab UI directly for the full logs, or consider reducing log verbosity in your CI configuration."
            )
        else:
            await session_manager.add_message(
                session_id,
                "assistant",
                f"Analysis failed: {error_msg}"
            )

async def analyze_quality_from_pipeline(session_id: str, project_key: str, gitlab_project_id: str, webhook_data: Dict):
    """Analyze quality issues when detected from pipeline failure"""
    try:
        log.info(f"Starting quality analysis from pipeline failure for session {session_id}")
        
        # First, try to get actual quality data from SonarQube
        from tools.sonarqube import get_project_issues, get_project_metrics, get_project_quality_gate_status
        
        # Get quality gate status
        quality_status = await get_project_quality_gate_status(project_key)
        
        # Check if there are actual quality issues or just no analysis
        project_status = quality_status.get("projectStatus", {})
        if project_status.get("status") == "NONE" or not project_status:
            log.warning(f"No quality gate configured or no analysis for {project_key}")
            
            # This is not a quality issue - it's a configuration/analysis issue
            # Update to pipeline failure
            await session_manager.update_session_metadata(
                session_id,
                {"session_type": "pipeline"}
            )
            
            await session_manager.add_message(
                session_id,
                "assistant",
                f"## ⚠️ SonarQube Analysis Issue\n\n"
                f"The pipeline failed at the SonarQube check stage, but this is not due to quality gate failure.\n\n"
                f"**Issue**: No SonarQube analysis results found for project '{project_key}'\n\n"
                f"**Possible reasons:**\n"
                f"1. SonarQube analysis was not performed\n"
                f"2. Project key mismatch between CI configuration and SonarQube\n"
                f"3. Authentication/permission issues\n"
                f"4. SonarQube server connectivity problems\n\n"
                f"**Recommended actions:**\n"
                f"1. Check the sonarqube-check job logs for specific errors\n"
                f"2. Verify the project key in your `sonar-project.properties` or CI configuration\n"
                f"3. Ensure SonarQube authentication token is valid\n"
                f"4. Verify the project exists in SonarQube\n\n"
                f"This appears to be a **pipeline configuration issue**, not a code quality issue."
            )
            return
        
        # Get issue counts by type
        bugs = await get_project_issues(project_key, types="BUG", limit=500)
        vulnerabilities = await get_project_issues(project_key, types="VULNERABILITY", limit=500)
        code_smells = await get_project_issues(project_key, types="CODE_SMELL", limit=500)
        
        # Get project metrics
        try:
            metrics = await get_project_metrics(project_key)
        except Exception as e:
            log.warning(f"Could not fetch metrics for {project_key}: {e}")
            metrics = {}
        
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
        
        # Prepare enhanced webhook data with quality information
        enhanced_webhook_data = {
            **webhook_data,
            "qualityGate": project_status
        }
        
        # Run quality analysis
        analysis = await quality_agent.analyze_quality_issues(
            session_id, project_key, gitlab_project_id, enhanced_webhook_data
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
            f"Quality analysis failed: {str(e)}"
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
        try:
            metrics = await get_project_metrics(project_key)
        except Exception as e:
            log.warning(f"Could not fetch metrics for {project_key}: {e}")
            metrics = {}
        
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
        error_msg = str(e)
        if "{" in error_msg or "}" in error_msg:
            error_msg = error_msg.replace("{", "{{").replace("}", "}}")

        log.error(f"Quality analysis failed: {e}", exc_info=True)
        await session_manager.add_message(
            session_id,
            "assistant",
            f"Analysis failed: {str(e)}"
        )

async def get_gitlab_project_id(sonarqube_key: str) -> Optional[str]:
    """Map SonarQube project key to GitLab project ID"""
    from tools.gitlab import get_gitlab_client
    
    log.info(f"Looking up GitLab project for SonarQube key: {sonarqube_key}")
    
    async with await get_gitlab_client() as client:
        try:
            # Strategy 1: Direct lookup by path (most common case)
            if "/" in sonarqube_key:
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

@router.post("/gitlab/pipeline-status")
async def handle_pipeline_status_webhook(request: Request):
    """Handle pipeline status updates to track fix effectiveness"""
    data = await request.json()
    
    if data.get("object_kind") != "pipeline":
        return {"status": "ignored"}
    
    # Check if this is a feature branch pipeline
    ref = data.get("object_attributes", {}).get("ref", "")
    if not ref.startswith("fix/"):
        return {"status": "ignored"}
    
    # Find the related session
    project_id = str(data.get("project", {}).get("id"))
    status = data.get("object_attributes", {}).get("status")
    
    # Update fix attempt status
    sessions = await session_manager.get_active_sessions()
    for session in sessions:
        if session.get("project_id") == project_id:
            fix_attempts = session.get("webhook_data", {}).get("fix_attempts", [])
            for attempt in fix_attempts:
                if attempt["branch"] == ref:
                    attempt["status"] = status
                    await session_manager.update_session_metadata(
                        session["id"], 
                        {"webhook_data": session["webhook_data"]}
                    )
                    
                    # If still failed, prepare for next iteration
                    if status == "failed":
                        await session_manager.add_message(
                            session["id"],
                            "system",
                            f"Fix attempt on branch {ref} failed. Pipeline still has issues."
                        )
    
    return {"status": "processed"}

@router.post("/webhooks/gitlab/pipeline-status")
async def handle_pipeline_status_webhook(request: Request):
    """Handle pipeline status updates to track fix effectiveness"""
    try:
        data = await request.json()
        
        if data.get("object_kind") != "pipeline":
            return {"status": "ignored"}
        
        status = data.get("object_attributes", {}).get("status")
        if status not in ["success", "failed"]:
            return {"status": "ignored"}
        
        pipeline_id = str(data.get("object_attributes", {}).get("id"))
        project_id = str(data.get("project", {}).get("id"))
        ref = data.get("object_attributes", {}).get("ref")
        
        # Check if this pipeline is related to any active session's MR
        async with await get_gitlab_client() as client:
            # Get pipeline details
            pipeline_response = await client.get(f"/projects/{project_id}/pipelines/{pipeline_id}")
            pipeline_data = pipeline_response.json()
            
            # Check if this is from a merge request
            if pipeline_data.get("source") == "merge_request_event":
                mr_iid = pipeline_data.get("merge_request", {}).get("iid")
                
                if mr_iid:
                    # Find session with this MR
                    sessions = await session_manager.get_active_sessions()
                    for session in sessions:
                        if (session.get("merge_request_id") == str(mr_iid) and 
                            session.get("project_id") == project_id):
                            
                            if status == "success":
                                await session_manager.mark_session_resolved(session["id"])
                                log.info(f"Marked session {session['id']} as resolved - MR pipeline succeeded")
                            else:
                                # Track failed attempt
                                await session_manager.track_fix_attempt(
                                    session["id"], 
                                    str(mr_iid), 
                                    ref,
                                    {"status": "failed"}
                                )
                            return {"status": "processed"}
            
            # Check if this is a post-merge pipeline on target branch
            elif pipeline_data.get("source") in ["push", "web"]:
                # Get recent MRs that were merged
                mr_response = await client.get(
                    f"/projects/{project_id}/merge_requests",
                    params={
                        "state": "merged",
                        "order_by": "updated_at",
                        "sort": "desc",
                        "per_page": 10
                    }
                )
                recent_mrs = mr_response.json()
                
                # Check if any merged MR is related to our sessions
                sessions = await session_manager.get_active_sessions()
                for mr in recent_mrs:
                    mr_id = str(mr.get("iid"))
                    merged_at = mr.get("merged_at")
                    
                    if merged_at:
                        # Check if pipeline started after merge
                        pipeline_created = pipeline_data.get("created_at")
                        if pipeline_created > merged_at:
                            for session in sessions:
                                if (session.get("merge_request_id") == mr_id and 
                                    session.get("project_id") == project_id and
                                    session.get("status") == "active"):
                                    
                                    if status == "success":
                                        await session_manager.mark_session_resolved(session["id"])
                                        log.info(f"Marked session {session['id']} as resolved - post-merge pipeline succeeded")
                                    return {"status": "processed"}
        
        return {"status": "processed"}
        
    except Exception as e:
        log.error(f"Pipeline status webhook failed: {e}")
        return {"status": "error", "message": str(e)}