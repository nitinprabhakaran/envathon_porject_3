from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any
import json
import uuid
from datetime import datetime
from loguru import logger
from utils.project_cache import project_cache
from agent.quality_agent import QualityAnalysisAgent
from db.session_manager import SessionManager
from tools.gitlab_tools import get_project_by_name

sonarqube_router = APIRouter()

# Initialize
quality_agent = QualityAnalysisAgent()
session_manager = SessionManager()

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
    
    # Extract actual project name from SonarQube key
    if sonarqube_key.startswith("envathon_"):
        gitlab_project_name = sonarqube_key[9:]
    else:
        gitlab_project_name = project_name
    
    # Look up GitLab project ID dynamically
    gitlab_project = await get_project_by_name(gitlab_project_name)
    gitlab_project_id = await project_cache.get_or_fetch(gitlab_project_name)
    if not gitlab_project_id:
        logger.error(f"Could not find GitLab project for {gitlab_project_name}")
        raise HTTPException(status_code=404, detail=f"GitLab project not found: {gitlab_project_name}")
    
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
        "message": "Quality analysis started",
        "ui_url": f"http://localhost:8501/?session={session_id}&tab=quality"
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