"""Session management API endpoints"""
import json
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from pydantic import BaseModel
from utils.logger import log
from db.session_manager import SessionManager
from agents.pipeline_agent import PipelineAgent
from agents.quality_agent import QualityAgent

router = APIRouter(prefix="/sessions", tags=["sessions"])

# Initialize components
session_manager = SessionManager()
pipeline_agent = PipelineAgent()
quality_agent = QualityAgent()

class MessageRequest(BaseModel):
    message: str

class MergeRequestRequest(BaseModel):
    session_id: str

@router.get("/active")
async def get_active_sessions():
    """Get all active sessions"""
    try:
        sessions = await session_manager.get_active_sessions()
        log.info(f"Retrieved {len(sessions)} active sessions")
        return sessions
    except Exception as e:
        log.error(f"Failed to get active sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{session_id}")
async def get_session(session_id: str):
    """Get session details"""
    try:
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to get session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{session_id}/message")
async def send_message(session_id: str, request: MessageRequest):
    """Send message to agent"""
    try:
        log.info(f"Received message for session {session_id}: {request.message[:50]}...")
        
        # Get session
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Add user message
        await session_manager.add_message(session_id, "user", request.message)
        
        # Get conversation history
        conversation_history = session.get("conversation_history", [])
        
        # Prepare context
        context = {
            "project_id": session.get("project_id"),
            "pipeline_id": session.get("pipeline_id"),
            "gitlab_project_id": session.get("project_id"),
            "sonarqube_key": session.get("webhook_data", {}).get("project", {}).get("key")
        }
        
        # Route to appropriate agent
        if session.get("session_type") == "quality":
            response = await quality_agent.handle_user_message(
                session_id, request.message, conversation_history, context
            )
        else:
            response = await pipeline_agent.handle_user_message(
                session_id, request.message, conversation_history, context
            )
        
        # Extract response text from agent result
        response_text = ""
        if isinstance(response, str):
            response_text = response
        elif hasattr(response, 'message'):
            response_text = response.message
        elif hasattr(response, 'messages') and response.messages:
            # Extract from messages list
            for msg in response.messages:
                if msg.get('role') == 'assistant':
                    content = msg.get('content', [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and 'text' in item:
                                response_text += item['text']
                    elif isinstance(content, str):
                        response_text = content
                    break
        
        if not response_text:
            response_text = str(response)
        
        # Add agent response
        await session_manager.add_message(session_id, "assistant", response_text)
        
        log.info(f"Generated response for session {session_id}")
        return {"response": response_text}
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to process message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{session_id}/create-mr")
async def create_merge_request(session_id: str):
    """Trigger merge request creation"""
    try:
        log.info(f"Creating MR for session {session_id}")
        
        # Get session
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Send MR creation message
        message = "Create a merge request with all the fixes we discussed"
        
        # Process through regular message handler
        await send_message(session_id, MessageRequest(message=message))
        
        return {"status": "success", "message": "Merge request creation initiated"}
        
    except Exception as e:
        log.error(f"Failed to create MR: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))