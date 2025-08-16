"""API client for Streamlit UI - Async version matching working reference"""
import httpx
import asyncio
from typing import Dict, List, Optional, Any
from utils.logger import log


class UnifiedAPIClient:
    def __init__(self):
        self.strands_base_url = "http://strands-agent:8000"
        self.webhook_base_url = "http://webhook-handler:8090"
        self.strands_url = self.strands_base_url  # Add alias for compatibility
        self.logger = log  # Add logger attribute for compatibility
        log.info(f"API client initialized - Strands: {self.strands_base_url}, Webhook: {self.webhook_base_url}")
    
    async def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Get all active sessions"""
        async with httpx.AsyncClient() as client:
            try:
                log.debug("Fetching active sessions")
                response = await client.get(f"{self.strands_url}/sessions/active")
                response.raise_for_status()
                sessions = response.json()
                log.info(f"Retrieved {len(sessions)} active sessions")
                return sessions
            except Exception as e:
                log.error(f"Failed to get active sessions: {e}")
                return []  # Return empty list instead of raising
    
    async def get_session_details(self, session_id: str) -> Dict[str, Any]:
        """Get session details"""
        async with httpx.AsyncClient() as client:
            try:
                log.debug(f"Fetching session {session_id}")
                response = await client.get(f"{self.strands_url}/sessions/{session_id}")
                response.raise_for_status()
                return response.json()
            except Exception as e:
                log.error(f"Failed to get session {session_id}: {e}")
                raise
    
    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session details - alias for compatibility"""
        return await self.get_session_details(session_id)
    
    async def send_message(self, session_id: str, message: str) -> dict:
        """Send a message to a session"""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.strands_base_url}/sessions/{session_id}/message",
                    json={"message": message},
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                self.logger.error(f"Failed to send message: {e}")
                raise

    async def list_subscriptions(self) -> list:
        """Get webhook subscriptions"""
        async with httpx.AsyncClient() as client:
            try:
                # Use trailing slash to avoid redirect
                response = await client.get(f"{self.webhook_base_url}/subscriptions/")
                response.raise_for_status()
                return response.json()
            except Exception as e:
                self.logger.error(f"Failed to get subscriptions: {e}")
                return []

    async def create_subscription(self, project_id: str, webhook_url: str) -> dict:
        """Create a webhook subscription"""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.webhook_base_url}/subscriptions/",
                    json={"project_id": project_id, "webhook_url": webhook_url}
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                self.logger.error(f"Failed to create subscription: {e}")
                raise

    async def delete_subscription(self, subscription_id: str) -> bool:
        """Delete a webhook subscription"""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.delete(
                    f"{self.webhook_base_url}/subscriptions/{subscription_id}"
                )
                response.raise_for_status()
                return True
            except Exception as e:
                self.logger.error(f"Failed to delete subscription: {e}")
                return False
    
    async def create_merge_request(self, session_id: str) -> Dict[str, Any]:
        """Trigger merge request creation"""
        async with httpx.AsyncClient() as client:
            try:
                log.info(f"Creating merge request for session {session_id}")
                response = await client.post(f"{self.strands_url}/sessions/{session_id}/create-mr")
                response.raise_for_status()
                return response.json()
            except Exception as e:
                log.error(f"Failed to create MR: {e}")
                raise
    
    def health_check(self) -> Dict[str, bool]:
        """Check health of both services"""
        import httpx
        
        health_status = {
            "strands_agent": False,
            "webhook_handler": False
        }
        
        # Check strands agent
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.strands_base_url}/health")
                health_status["strands_agent"] = response.status_code == 200
        except Exception as e:
            log.error(f"Strands agent health check failed: {e}")
        
        # Check webhook handler
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.webhook_base_url}/health")
                health_status["webhook_handler"] = response.status_code == 200
        except Exception as e:
            log.error(f"Webhook handler health check failed: {e}")
        
        return health_status