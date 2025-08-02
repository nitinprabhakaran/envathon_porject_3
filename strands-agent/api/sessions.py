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
        
        # Extract text from response - handle Strands agent response format
        response_text = extract_text_from_response(response)
        
        if not response_text:
            response_text = str(response)
        
        # Extract and store MR URL if present
        mr_url = None
        mr_id = None
        
        # Check for MR URL in the response text
        mr_url_match = re.search(r'https?://[^\s<>"{}|\\^`\[\]]+/merge_requests/\d+', response_text)
        if mr_url_match:
            mr_url = mr_url_match.group(0)
            mr_id = mr_url.split('/')[-1]
        
        # Also check if the agent returned MR info in tool response
        if "web_url" in response_text:
            # Extract web_url from tool response
            web_url_match = re.search(r'"web_url":\s*"([^"]+)"', response_text)
            if web_url_match:
                mr_url = web_url_match.group(1)
                mr_id = mr_url.split('/')[-1] if mr_url else None
        
        if mr_url:
            await session_manager.update_session_metadata(
                session_id,
                {
                    "merge_request_url": mr_url,
                    "merge_request_id": mr_id
                }
            )
        
        # Add agent response - store only the text, not the full structure
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
    
    # Handle Strands agent response
    if hasattr(response, 'message'):
        return response.message
    
    # Handle dict with content array
    if isinstance(response, dict) and "content" in response:
        content = response["content"]
        if isinstance(content, list):
            return "".join(item.get("text", "") for item in content if isinstance(item, dict))
        return str(content)
    
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


async def store_file_analysis(self, session_id: str, file_path: str, original_content: str, proposed_changes: str):
    """Store file analysis for a specific file in a session"""
    async with self.get_connection() as conn:
        # Store in a JSONB field in sessions table
        current = await conn.fetchval(
            "SELECT webhook_data FROM sessions WHERE id = $1",
            session_id
        )
        
        webhook_data = json.loads(current) if current else {}
        
        # Initialize file_analysis if not exists
        if 'file_analysis' not in webhook_data:
            webhook_data['file_analysis'] = {}
        
        # Store file data
        webhook_data['file_analysis'][file_path] = {
            'original_content': original_content,
            'proposed_changes': proposed_changes,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        await conn.execute(
            "UPDATE sessions SET webhook_data = $2::jsonb WHERE id = $1",
            session_id, json.dumps(webhook_data)
        )
        log.info(f"Stored file analysis for {file_path} in session {session_id}")

async def get_file_analysis(self, session_id: str) -> Dict[str, Any]:
    """Get all file analysis for a session"""
    session = await self.get_session(session_id)
    if session:
        return session.get('webhook_data', {}).get('file_analysis', {})
    return {}