"""Webhook Manager for auto-configuring project webhooks"""
import httpx
from typing import List, Dict, Any
from utils.logger import log
from config import settings

class WebhookManager:
    """Manage webhook subscriptions for GitLab/SonarQube projects"""
    
    async def setup_gitlab_webhooks(
        self,
        project_id: str,
        project_url: str,
        access_token: str,
        webhook_url: str,
        webhook_secret: str,
        events: List[str]
    ) -> List[str]:
        """Configure GitLab webhooks for a project"""
        webhook_ids = []
        
        async with httpx.AsyncClient() as client:
            headers = {"PRIVATE-TOKEN": access_token}
            
            # Configure pipeline webhook
            if "pipeline" in events:
                response = await client.post(
                    f"{project_url}/api/v4/projects/{project_id}/hooks",
                    headers=headers,
                    json={
                        "url": webhook_url,
                        "token": webhook_secret,
                        "pipeline_events": True,
                        "push_events": False,
                        "merge_requests_events": "merge_request" in events
                    }
                )
                if response.status_code == 201:
                    webhook_ids.append(str(response.json()["id"]))
                    log.info(f"Created GitLab webhook for project {project_id}")
        
        return webhook_ids
    
    async def setup_sonarqube_webhooks(
        self,
        project_id: str,
        project_url: str,
        access_token: str,
        webhook_url: str,
        webhook_secret: str
    ) -> List[str]:
        """Configure SonarQube webhooks"""
        webhook_ids = []
        
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {access_token}"}
            
            response = await client.post(
                f"{project_url}/api/webhooks/create",
                headers=headers,
                json={
                    "name": f"cicd-assistant-{project_id}",
                    "url": webhook_url,
                    "project": project_id,
                    "secret": webhook_secret
                }
            )
            if response.status_code == 200:
                webhook_ids.append(response.json()["webhook"]["key"])
                log.info(f"Created SonarQube webhook for project {project_id}")
        
        return webhook_ids
    
    async def remove_webhooks(
        self,
        project_type: str,
        project_url: str,
        access_token: str,
        webhook_ids: List[str]
    ):
        """Remove webhooks when subscription expires"""
        async with httpx.AsyncClient() as client:
            if project_type == "gitlab":
                headers = {"PRIVATE-TOKEN": access_token}
                for webhook_id in webhook_ids:
                    await client.delete(
                        f"{project_url}/api/v4/hooks/{webhook_id}",
                        headers=headers
                    )
            elif project_type == "sonarqube":
                headers = {"Authorization": f"Bearer {access_token}"}
                for webhook_id in webhook_ids:
                    await client.post(
                        f"{project_url}/api/webhooks/delete",
                        headers=headers,
                        json={"webhook": webhook_id}
                    )