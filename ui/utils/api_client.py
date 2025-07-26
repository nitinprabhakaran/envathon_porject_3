import httpx
import os
from typing import Dict, Any, List

class APIClient:
    """API client for communicating with Strands Agent"""
    
    def __init__(self):
        self.base_url = os.getenv("STRANDS_API_URL", "http://localhost:8000")
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
    
    async def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Get all active sessions"""
        try:
            response = await self.client.get("/api/sessions/active")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error getting active sessions: {e}")
            return []
    
    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get specific session details"""
        try:
            response = await self.client.get(f"/api/sessions/{session_id}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error getting session {session_id}: {e}")
            return {}
    
    async def send_message(self, session_id: str, message: str) -> Dict[str, Any]:
        """Send a message to the agent for a specific session"""
        try:
            response = await self.client.post(
                f"/api/sessions/{session_id}/message",
                json={"message": message}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error sending message: {e}")
            return {"error": str(e)}
    
    async def apply_fix(self, session_id: str, fix_id: str) -> Dict[str, Any]:
        """Apply a suggested fix"""
        try:
            response = await self.client.post(
                f"/api/sessions/{session_id}/apply-fix",
                json={"fix_id": fix_id}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error applying fix: {e}")
            return {"error": str(e)}
    
    async def create_merge_request(
        self, 
        session_id: str, 
        fix_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a merge request for a fix"""
        try:
            response = await self.client.post(
                f"/api/sessions/{session_id}/create-mr",
                json=fix_data
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error creating MR: {e}")
            return {"error": str(e)}
    
    async def get_analysis_progress(self, session_id: str) -> Dict[str, Any]:
        """Get analysis progress for a session"""
        try:
            response = await self.client.get(f"/progress/{session_id}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error getting progress: {e}")
            return {"status": "unknown", "progress": 0}
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()