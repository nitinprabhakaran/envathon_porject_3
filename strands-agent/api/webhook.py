from fastapi import APIRouter, HTTPException, Request, Header
from typing import Dict, Any, Optional
import hmac
import hashlib
import json
import os
from datetime import datetime
from loguru import logger
import asyncio

from agent.core import CICDFailureAgent
from db.session_manager import SessionManager

webhook_router = APIRouter()

# Initialize agent
agent = CICDFailureAgent()
session_manager = SessionManager()

# Progress tracking
analysis_progress = {}

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

async def update_progress(session_id: str, status: str, progress: int, message: str):
    """Update analysis progress"""
    analysis_progress[session_id] = {
        "status": status,
        "progress": progress,
        "message": message,
        "timestamp": datetime.utcnow().isoformat()
    }
    logger.info(f"Progress: {session_id} - {progress}% - {message}")

@webhook_router.get("/progress/{session_id}")
async def get_progress(session_id: str):
    """Get analysis progress for a session"""
    return analysis_progress.get(session_id, {
        "status": "unknown",
        "progress": 0,
        "message": "No progress data available"
    })

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
    
    await update_progress(session_id, "initializing", 5, "Creating session...")
    
    # Create or get session - THIS IS KEY
    session = await session_manager.create_or_get_session(
        session_id=session_id,
        project_id=project_id,
        pipeline_id=pipeline_id,
        commit_hash=data.get("commit", {}).get("sha")
    )
    
    # Use the actual session ID (might be different if session already existed)
    actual_session_id = session['id']
    
    await update_progress(actual_session_id, "processing", 10, "Storing metadata...")
    
    # Extract failed job info
    failed_job_name = "unknown"
    failed_stage = "unknown"
    for build in data.get("builds", []):
        if build.get("status") == "failed":
            failed_job_name = build.get("name", "unknown")
            failed_stage = build.get("stage", "unknown")
            break
    
    # Store webhook data and metadata - IMPORTANT: Set all required fields
    await session_manager.update_metadata(actual_session_id, {
        "webhook_data": data,
        "failed_at": datetime.utcnow().isoformat(),
        "branch": data["object_attributes"]["ref"],
        "pipeline_source": data["object_attributes"]["source"],
        "project_name": data["project"]["name"],
        "job_name": failed_job_name,
        "failed_stage": failed_stage,
        "error_type": "build_failure",
        "commit_sha": data["object_attributes"]["sha"],
        "pipeline_url": data["object_attributes"]["url"],
        "error_signature": f"Pipeline {pipeline_id} failed at {failed_stage} stage"
    })
    
    # Add initial message to conversation history
    await session_manager.update_conversation(
        actual_session_id,
        {
            "role": "system",
            "content": f"Pipeline failure detected for {data['project']['name']} pipeline #{pipeline_id}",
            "timestamp": datetime.utcnow().isoformat()
        }
    )
    
    await update_progress(actual_session_id, "analyzing", 20, "Starting AI analysis...")
    
    # Run analysis in background
    asyncio.create_task(run_analysis_with_progress(actual_session_id, data))
    
    # Return the session ID for UI redirect
    return {
        "status": "analyzing",
        "session_id": actual_session_id,
        "message": "Analysis started in background",
        "ui_url": f"http://localhost:8501/?session={actual_session_id}"
    }

async def run_analysis_with_progress(session_id: str, webhook_data: Dict[str, Any]):
    """Run analysis with progress updates"""
    try:
        # Update progress during analysis
        await update_progress(session_id, "analyzing", 30, "Retrieving pipeline details...")
        
        # Set a progress callback on the agent
        original_call = agent.agent.__call__
        tool_count = 0
        
        async def progress_wrapper(*args, **kwargs):
            nonlocal tool_count
            result = await original_call(*args, **kwargs)
            tool_count += 1
            progress = min(30 + (tool_count * 5), 90)
            await update_progress(session_id, "analyzing", progress, f"Running analysis step {tool_count}...")
            return result
            
        agent.agent.__call__ = progress_wrapper
        
        # Run analysis
        analysis_result = await agent.analyze_failure(
            session_id=session_id,
            webhook_data=webhook_data
        )
        
        # Restore original method
        agent.agent.__call__ = original_call
        
        await update_progress(session_id, "complete", 100, "Analysis complete!")
        
        # Post comment to GitLab
        if analysis_result.get("cards"):
            comment = format_gitlab_comment(analysis_result)
            logger.info(f"Would post comment to pipeline {webhook_data['object_attributes']['id']}")
            # In production, you would actually post the comment using GitLab API
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        await update_progress(session_id, "failed", 0, f"Analysis failed: {str(e)}")
        
        # Add error to conversation history
        await session_manager.update_conversation(
            session_id,
            {
                "role": "assistant",
                "content": f"Failed to analyze pipeline: {str(e)}",
                "cards": [{
                    "type": "error",
                    "title": "Analysis Failed",
                    "content": f"Failed to analyze pipeline: {str(e)}",
                    "actions": [{"label": "Retry", "action": "retry_analysis"}]
                }],
                "timestamp": datetime.utcnow().isoformat()
            }
        )

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