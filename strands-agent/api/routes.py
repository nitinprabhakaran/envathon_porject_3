from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from pydantic import BaseModel
from loguru import logger

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

@api_router.get("/sessions/active")
async def get_active_sessions():
    """Get all active sessions"""
    try:
        sessions = await session_manager.get_active_sessions()
        return sessions
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
        return session
    except Exception as e:
        logger.error(f"Failed to get session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/sessions/{session_id}/message")
async def send_message(session_id: str, request: MessageRequest):
    """Send a message to the agent for a specific session"""
    try:
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