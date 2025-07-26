from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from pydantic import BaseModel
from loguru import logger
import json
from datetime import datetime

from agent.core import CICDFailureAgent
from db.session_manager import SessionManager

api_router = APIRouter()

# Initialize
agent = CICDFailureAgent()
session_manager = SessionManager()

class MessageRequest(BaseModel):
    message: str

class ApplyFixRequest(BaseModel):
    fix_id: str
    fix_data: Dict[str, Any]

def serialize_session(session: Dict[str, Any]) -> Dict[str, Any]:
    """Properly serialize session data for API response"""
    # Convert any datetime objects to strings
    for key in ['created_at', 'last_activity', 'expires_at']:
        if key in session and session[key]:
            if hasattr(session[key], 'isoformat'):
                session[key] = session[key].isoformat()
    
    # Ensure conversation_history is a list
    if 'conversation_history' in session:
        if isinstance(session['conversation_history'], str):
            try:
                session['conversation_history'] = json.loads(session['conversation_history'])
            except:
                session['conversation_history'] = []
        elif session['conversation_history'] is None:
            session['conversation_history'] = []
    
    # Ensure other JSON fields are properly loaded
    for json_field in ['applied_fixes', 'successful_fixes', 'tools_called', 'user_feedback', 'webhook_data']:
        if json_field in session:
            if isinstance(session[json_field], str):
                try:
                    session[json_field] = json.loads(session[json_field])
                except:
                    session[json_field] = [] if json_field.endswith('fixes') or json_field == 'tools_called' else {}
            elif session[json_field] is None:
                session[json_field] = [] if json_field.endswith('fixes') or json_field == 'tools_called' else {}
    
    # Extract metadata from webhook_data if available
    if 'webhook_data' in session and session['webhook_data']:
        webhook_data = session['webhook_data']
        if isinstance(webhook_data, dict):
            # Extract key fields
            if 'project' in webhook_data:
                session['project_name'] = webhook_data['project'].get('name', session.get('project_name'))
            if 'object_attributes' in webhook_data:
                attrs = webhook_data['object_attributes']
                session['branch'] = attrs.get('ref', session.get('branch'))
                session['pipeline_source'] = attrs.get('source', session.get('pipeline_source'))
                session['pipeline_url'] = attrs.get('url', session.get('pipeline_url'))
    
    return session

@api_router.get("/sessions/active")
async def get_active_sessions():
    """Get all active sessions"""
    try:
        sessions = await session_manager.get_active_sessions()
        # Serialize each session
        serialized_sessions = [serialize_session(session) for session in sessions]
        logger.info(f"Returning {len(serialized_sessions)} active sessions")
        return serialized_sessions
    except Exception as e:
        logger.error(f"Failed to get active sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get specific session details"""
    try:
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Serialize the session
        serialized_session = serialize_session(session)
        logger.info(f"Returning session {session_id} with project_id={serialized_session.get('project_id')}")
        return serialized_session
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/sessions/{session_id}/message")
async def send_message(session_id: str, request: MessageRequest):
    """Send a message to the agent for a specific session"""
    try:
        # Get session first to ensure it exists
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        response = await agent.continue_conversation(
            session_id=session_id,
            user_message=request.message
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to process message: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/sessions/{session_id}/apply-fix")
async def apply_fix(session_id: str, request: ApplyFixRequest):
    """Apply a suggested fix"""
    try:
        # Record the fix application
        await session_manager.add_applied_fix(
            session_id,
            {
                "fix_id": request.fix_id,
                "fix_data": request.fix_data,
                "status": "applying"
            }
        )
        
        # In production, this would trigger actual fix application
        # For now, return success
        return {
            "status": "success",
            "fix_id": request.fix_id,
            "message": "Fix application initiated"
        }
    except Exception as e:
        logger.error(f"Failed to apply fix: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/sessions/{session_id}/create-mr")
async def create_merge_request(session_id: str, fix_data: Dict[str, Any]):
    """Create a merge request for a fix"""
    try:
        # This would use GitLab tools to create actual MR
        # For now, return mock response
        return {
            "status": "success",
            "merge_request": {
                "id": "123",
                "url": "https://gitlab.example.com/project/merge_requests/123",
                "title": fix_data.get("title", "Fix pipeline issue")
            }
        }
    except Exception as e:
        logger.error(f"Failed to create MR: {e}")
        raise HTTPException(status_code=500, detail=str(e))