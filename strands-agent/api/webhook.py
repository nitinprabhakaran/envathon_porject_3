from fastapi import APIRouter, HTTPException, Request, Header
from typing import Dict, Any, Optional
import hmac
import hashlib
import json
import os
from datetime import datetime
from loguru import logger

from agent.core import CICDFailureAgent
from db.session_manager import SessionManager

webhook_router = APIRouter()

# Initialize agent
agent = CICDFailureAgent()
session_manager = SessionManager()

def verify_gitlab_token(token: str, body: bytes, gitlab_token: str) -> bool:
    """Verify GitLab webhook token"""
    if not gitlab_token:
        return True
    
    expected = hmac.new(
        gitlab_token.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(token, expected)

@webhook_router.post("/gitlab")
async def handle_gitlab_webhook(
    request: Request,
    x_gitlab_token: Optional[str] = Header(None)
):
    """Handle GitLab pipeline failure webhooks"""
    
    # Get raw body
    body = await request.body()
    
    # Verify webhook token
    gitlab_webhook_token = os.getenv("GITLAB_WEBHOOK_TOKEN")
    if gitlab_webhook_token and x_gitlab_token:
        if not verify_gitlab_token(x_gitlab_token, body, gitlab_webhook_token):
            raise HTTPException(status_code=401, detail="Invalid webhook token")
    
    # Parse webhook data
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    # Check if this is a pipeline failure event
    if data.get("object_kind") != "pipeline":
        return {"status": "ignored", "reason": "Not a pipeline event"}
    
    if data.get("object_attributes", {}).get("status") != "failed":
        return {"status": "ignored", "reason": "Not a failure event"}
    
    # Extract key information
    project_id = str(data["project"]["id"])
    pipeline_id = str(data["object_attributes"]["id"])
    
    # Create session ID using UUID
    import uuid
    session_id = str(uuid.uuid4())
    
    # Create or get session
    session = await session_manager.create_or_get_session(
        session_id=session_id,
        project_id=project_id,
        pipeline_id=pipeline_id,
        commit_hash=data.get("commit", {}).get("sha")
    )
    
    try:
        job_name = agent._extract_failed_job_name(data)
    except:
        job_name = "unknown"

    # Store webhook data
    await session_manager.update_metadata(session_id, {
        "webhook_data": data,
        "failed_at": datetime.utcnow().isoformat(),
        "branch": data["object_attributes"]["ref"],
        "pipeline_source": data["object_attributes"]["source"],
        "project_name": data["project"]["name"],
        "job_name": job_name,
    })
    
    # Trigger analysis
    try:
        analysis_result = await agent.analyze_failure(
            session_id=session_id,
            webhook_data=data
        )
        
        # Post comment to GitLab
        if analysis_result.get("cards"):
            comment = format_gitlab_comment(analysis_result)
            # This would use GitLab API to post comment
            logger.info(f"Would post comment to pipeline {pipeline_id}")
        
        return {
            "status": "success",
            "session_id": session_id,
            "analysis": analysis_result
        }
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return {
            "status": "error",
            "session_id": session_id,
            "error": str(e)
        }

def format_gitlab_comment(analysis_result: Dict[str, Any]) -> str:
    """Format analysis result as GitLab comment"""
    comment_parts = [
        "## 🔍 Pipeline Failure Analysis\n"
    ]
    
    # Add session link
    session_id = analysis_result["session_id"]
    ui_url = f"http://localhost:8501/?session={session_id}"
    comment_parts.append(f"[View Interactive Analysis]({ui_url})\n")
    
    # Add cards content
    for card in analysis_result.get("cards", []):
        if card["type"] == "analysis":
            comment_parts.append(f"### {card['title']}")
            comment_parts.append(card.get('content', ''))
        elif card["type"] == "solution":
            comment_parts.append(f"\n### 💡 {card['title']}")
            comment_parts.append(f"**Confidence:** {card.get('confidence', 'N/A')}%")
            comment_parts.append(f"**Estimated Time:** {card.get('estimated_time', 'Unknown')}")
            comment_parts.append(f"\n{card.get('content', '')}")
    
    comment_parts.append(f"\n---\n*Session ID: `{session_id}` | Continue conversation in the UI*")
    
    return "\n".join(comment_parts)