from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any, Optional
import json
import uuid
from datetime import datetime
from loguru import logger
import httpx
import os

from agent.quality_agent import QualityAnalysisAgent
from db.session_manager import SessionManager

sonarqube_router = APIRouter()

# Initialize
quality_agent = QualityAnalysisAgent()
session_manager = SessionManager()

async def get_gitlab_project_id(project_name: str) -> Optional[str]:
    """Get GitLab project ID from project name"""
    gitlab_url = os.getenv("GITLAB_URL", "http://gitlab:80")
    gitlab_token = os.getenv("GITLAB_TOKEN", "")
    
    headers = {"PRIVATE-TOKEN": gitlab_token} if gitlab_token else {}
    
    async with httpx.AsyncClient() as client:
        try:
            # Search for project
            response = await client.get(
                f"{gitlab_url}/api/v4/projects",
                params={"search": project_name},
                headers=headers
            )
            
            if response.status_code == 200:
                projects = response.json()
                # Find in envathon group
                for project in projects:
                    if project.get("path_with_namespace") == f"envathon/{project_name}":
                        return str(project["id"])
        except Exception as e:
            logger.error(f"Failed to get GitLab project ID: {e}")
    
    return None

@sonarqube_router.post("/sonarqube")
async def handle_sonarqube_webhook(request: Request):
    """Handle SonarQube quality gate failure webhooks"""
    
    # Parse webhook data
    try:
        data = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse SonarQube webhook: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Check if quality gate failed
    quality_gate = data.get("qualityGate", {})
    if quality_gate.get("status") != "ERROR":
        return {"status": "ignored", "reason": "Quality gate passed"}
    
    # Extract project information
    project = data.get("project", {})
    sonarqube_key = project.get("key", "")
    project_name = project.get("name", "Unknown")
    
    # Since SonarQube key = project name now, use it directly
    gitlab_project_id = await get_gitlab_project_id(sonarqube_key)

    if not gitlab_project_id:
        logger.error(f"Could not find GitLab project for SonarQube project {sonarqube_key}")
        raise HTTPException(status_code=404, detail=f"GitLab project not found for {project_name}")

    # Check for existing active quality session for this project
    existing_session = await session_manager.check_existing_quality_session(gitlab_project_id)
    if existing_session:
        logger.info(f"Existing quality session found for project {gitlab_project_id}")
        return {
            "status": "existing",
            "session_id": str(existing_session['id']),
            "message": "Using existing quality session"
        }
    
    # Create session
    session_id = str(uuid.uuid4())
    
    # Create quality session
    session = await session_manager.create_quality_session(
        session_id=session_id,
        project_id=gitlab_project_id,
        project_name=project_name,
        quality_gate_status=quality_gate.get("status", "ERROR")
    )
    
    # Store webhook data
    await session_manager.update_metadata(session_id, {
        "webhook_data": data,
        "sonarqube_key": sonarqube_key,
        "gitlab_project_id": gitlab_project_id,
        "analyzed_at": data.get("analysedAt"),
        "branch": data.get("branch", {}).get("name", "main"),
    })
    
    # Count issues by severity
    conditions = quality_gate.get("conditions", [])
    critical_issues = sum(1 for c in conditions if c.get("status") == "ERROR" and "critical" in c.get("metric", "").lower())
    major_issues = sum(1 for c in conditions if c.get("status") == "ERROR" and "major" in c.get("metric", "").lower())
    total_issues = len([c for c in conditions if c.get("status") == "ERROR"])
    
    # Update quality metrics
    await session_manager.update_quality_metrics(
        session_id=session_id,
        total_issues=total_issues,
        critical_issues=critical_issues,
        major_issues=major_issues
    )
    
    # Add initial message
    await session_manager.update_conversation(
        session_id,
        {
            "role": "system",
            "content": f"Quality gate failure detected for {project_name}",
            "timestamp": datetime.utcnow().isoformat()
        }
    )
    
    # Run quality analysis in background
    import asyncio
    asyncio.create_task(run_quality_analysis(session_id, data, sonarqube_key, gitlab_project_id))
    
    return {
        "status": "analyzing",
        "session_id": session_id,
        "message": "Quality analysis started"
    }

async def run_quality_analysis(session_id: str, webhook_data: Dict[str, Any], sonarqube_key: str, gitlab_project_id: str):
    """Run quality analysis with proper context"""
    try:
        # Pass both keys in webhook data
        webhook_data["_sonarqube_key"] = sonarqube_key
        webhook_data["_gitlab_project_id"] = gitlab_project_id
        
        result = await quality_agent.analyze_quality_issues(
            session_id=session_id,
            webhook_data=webhook_data
        )
        
        logger.info(f"Quality analysis complete for session {session_id}")
        
    except Exception as e:
        logger.error(f"Quality analysis failed: {e}", exc_info=True)
        
        # Add error to conversation
        await session_manager.update_conversation(
            session_id,
            {
                "role": "assistant",
                "content": f"Failed to analyze quality issues: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }
        )