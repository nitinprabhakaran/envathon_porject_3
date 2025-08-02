"""Session management API endpoints"""
import json
import re
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
        
        # Get session context
        context = await session_manager.get_session_context(session_id)
        if not context:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Add user message
        await session_manager.add_message(session_id, "user", request.message)
        
        # Get conversation history
        session = await session_manager.get_session(session_id)
        conversation_history = session.get("conversation_history", [])
        
        # Route to appropriate agent
        if context.session_type == "quality":
            response = await quality_agent.handle_user_message(
                session_id, request.message, conversation_history, context
            )
        else:
            response = await pipeline_agent.handle_user_message(
                session_id, request.message, conversation_history, context
            )
        
        # Generic response extraction
        response_text = extract_text_from_response(response)
        
        # Extract and store MR URL if present
        mr_url = None
        mr_url_match = re.search(r'https?://[^\s<>"{}|\\^`\[\]]+/merge_requests/\d+', response_text)
        if mr_url_match:
            mr_url = mr_url_match.group(0)
            mr_id = mr_url.split('/')[-1]
            
            await session_manager.update_session_metadata(
                session_id,
                {
                    "merge_request_url": mr_url,
                    "merge_request_id": mr_id
                }
            )
        
        # Add agent response
        await session_manager.add_message(session_id, "assistant", response_text)
        
        log.info(f"Generated response for session {session_id}, MR URL: {mr_url}")
        
        return {
            "response": response_text,
            "merge_request_url": mr_url
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to process message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

def extract_text_from_response(response):
    """Extract text from any response format"""
    if isinstance(response, str):
        return response
    
    if hasattr(response, 'message'):
        return response.message
    
    if isinstance(response, dict):
        # Try content field
        if "content" in response:
            content = response["content"]
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        texts.append(item["text"])
                return "".join(texts)
            elif isinstance(content, str):
                return content
        # Try message field
        elif "message" in response:
            return response["message"]
    
    return str(response)

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
        message = "Create a merge request with all the fixes we discussed. Make sure to include the MR URL in your response."
        
        # Process through regular message handler
        result = await send_message(session_id, MessageRequest(message=message))
        
        return {
            "status": "success",
            "message": "Merge request creation initiated",
            "merge_request_url": result.get("merge_request_url")
        }
        
    except Exception as e:
        log.error(f"Failed to create MR: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

def extract_response_text(response) -> str:
    """Extract text from various response formats"""
    if isinstance(response, str):
        return response
    
    if hasattr(response, 'message') and isinstance(response.message, str):
        return response.message
    
    if hasattr(response, 'content') and isinstance(response.content, str):
        return response.content
    
    if isinstance(response, dict):
        # Handle content array format
        if "content" in response:
            content = response["content"]
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        texts.append(item["text"])
                return "".join(texts)
            return str(content)
        elif "message" in response:
            return response["message"]
    
    # Handle response with nested structure
    if hasattr(response, '__dict__'):
        for attr in ['message', 'content', 'text']:
            if hasattr(response, attr):
                val = getattr(response, attr)
                if isinstance(val, str):
                    return val
    
    return str(response)

def extract_files_from_response(response_text: str) -> Dict[str, str]:
    """Extract file paths mentioned in the response"""
    files = {}
    
    # Look for patterns like "File: path/to/file.ext" or "Modified: file.yml"
    file_patterns = [
        r'(?:File|Modified|Changed|Updated):\s*`?([^\s`]+)`?',
        r'(?:```[\w]*\n)?(?:# )?([^\s]+\.[a-z]+)',
    ]
    
    for pattern in file_patterns:
        matches = re.findall(pattern, response_text)
        for match in matches:
            if '.' in match and not match.startswith('http'):
                files[match] = "modified"
    
    return files