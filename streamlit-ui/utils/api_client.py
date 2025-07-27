"""API client for Streamlit UI"""
import httpx
import os
from typing import Dict, Any, List
from utils.logger import setup_logger

log = setup_logger()

class APIClient:
    def __init__(self):
        self.base_url = os.getenv("STREAMLIT_API_URL", "http://localhost:8000")
        log.info(f"API client initialized with base URL: {self.base_url}")
    
    async def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Get all active sessions"""
        async with httpx.AsyncClient() as client:
            try:
                log.debug("Fetching active sessions")
                response = await client.get(f"{self.base_url}/sessions/active")
                response.raise_for_status()
                sessions = response.json()
                log.info(f"Retrieved {len(sessions)} active sessions")
                return sessions
            except Exception as e:
                log.error(f"Failed to get active sessions: {e}")
                return []
    
    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session details"""
        async with httpx.AsyncClient() as client:
            try:
                log.debug(f"Fetching session {session_id}")
                response = await client.get(f"{self.base_url}/sessions/{session_id}")
                response.raise_for_status()
                return response.json()
            except Exception as e:
                log.error(f"Failed to get session {session_id}: {e}")
                raise
    
    async def send_message(self, session_id: str, message: str) -> Dict[str, Any]:
        """Send message to agent"""
        async with httpx.AsyncClient() as client:
            try:
                log.info(f"Sending message to session {session_id}: {message[:50]}...")
                response = await client.post(
                    f"{self.base_url}/sessions/{session_id}/message",
                    json={"message": message},
                    timeout=60.0
                )
                response.raise_for_status()
                result = response.json()
                log.info(f"Received response for session {session_id}")
                return result
            except Exception as e:
                log.error(f"Failed to send message: {e}")
                raise
    
    async def create_merge_request(self, session_id: str) -> Dict[str, Any]:
        """Trigger merge request creation"""
        async with httpx.AsyncClient() as client:
            try:
                log.info(f"Creating merge request for session {session_id}")
                response = await client.post(f"{self.base_url}/sessions/{session_id}/create-mr")
                response.raise_for_status()
                return response.json()
            except Exception as e:
                log.error(f"Failed to create MR: {e}")
                raise