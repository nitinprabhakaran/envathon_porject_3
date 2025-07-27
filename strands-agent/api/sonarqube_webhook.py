from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any
import json
import uuid
from datetime import datetime
from loguru import logger

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
    project_key = project.get("key", "")
    project_name = project.get("name", "Unknown")
    
    # Extract project_id from key (format: envathon_project-name)
    # This is a simplified approach - adjust based on your project structure
    if project_key.startswith("envathon_"):
        project_name_from_key = project_key[9:]  # Remove "envathon_" prefix
    else:
        project_name_from_key = project_name
    
    # For now, use the project name as the ID (in production, you'd look this up)
    project_id = project_name_from_key
    
    # Create session
    session_id = str(uuid.uuid4())
    
    # Create quality session
    session = await session_manager.create_quality_session(
        session_id=session_id,
        project_id=project_id,
        project_name=project_name,
        quality_gate_status=quality_gate.get("status", "ERROR")
    )
    
    # Store webhook data
    await session_manager.update_metadata(session_id, {
        "webhook_data": data,
        "project_key": project_key,
        "analyzed_at": data.get("analysedAt"),
        "branch": data.get("branch", {}).get("name", "main")
    })
    
    # Count issues by severity
    critical_issues = sum(1 for c in quality_gate.get("conditions", []) 
                         if c.get("status") == "ERROR" and "critical" in c.get("metric", "").lower())
    major_issues = sum(1 for c in quality_gate.get("conditions", []) 
                      if c.get("status") == "ERROR" and "major" in c.get("metric", "").lower())
    total_issues = len([c for c in quality_gate.get("conditions", []) if c.get("status") == "ERROR"])
    
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
    asyncio.create_task(run_quality_analysis(session_id, data))
    
    return {
        "status": "analyzing",
        "session_id": session_id,
        "message": "Quality analysis started",
        "ui_url": f"http://localhost:8501/?session={session_id}&tab=quality"
    }

async def run_quality_analysis(session_id: str, webhook_data: Dict[str, Any]):
    """Run quality analysis with the agent"""
    try:
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
                "cards": [{
                    "type": "error",
                    "title": "Analysis Failed",
                    "content": f"Failed to analyze quality issues: {str(e)}",
                    "actions": [{"label": "Retry", "action": "retry_analysis"}]
                }],
                "timestamp": datetime.utcnow().isoformat()
            }
        )

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
    project_key = project.get("key", "")
    project_name = project.get("name", "Unknown")
    
    # Extract actual project name from SonarQube key
    if project_key.startswith("envathon_"):
        actual_project_name = project_key[9:]  # Remove prefix
    else:
        actual_project_name = project_name
    
    # Look up GitLab project ID dynamically
    gitlab_project = await get_project_by_name(actual_project_name)
    if not gitlab_project:
        logger.error(f"Could not find GitLab project for {actual_project_name}")
        gitlab_project_id = actual_project_name  # Fallback
    else:
        gitlab_project_id = gitlab_project["id"]
    
    # Create session
    session_id = str(uuid.uuid4())
    
    # Create quality session
    session = await session_manager.create_quality_session(
        session_id=session_id,
        project_id=gitlab_project_id,
        project_name=project_name,
        quality_gate_status=quality_gate.get("status", "ERROR")
    )
    
    # Store webhook data with both IDs
    await session_manager.update_metadata(session_id, {
        "webhook_data": data,
        "sonarqube_project_key": project_key,
        "gitlab_project_id": gitlab_project_id,
        "analyzed_at": data.get("analysedAt"),
        "branch": data.get("branch", {}).get("name", "main"),
    })