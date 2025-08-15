"""Event Processor for webhook events"""
import json
import uuid
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from utils.logger import log
from config import settings
from db.database import Database
from services.queue_publisher import QueuePublisher

class EventProcessor:
    """Process incoming webhook events"""
    
    def __init__(self):
        self.db = Database()
        self.queue_publisher = QueuePublisher()
    
    async def process_gitlab_webhook(
        self,
        data: Dict[str, Any],
        subscription_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process GitLab webhook and create session"""
        event_type = data.get("object_kind")
        
        if event_type != "pipeline":
            return {"status": "ignored", "reason": "Not a pipeline event"}
        
        pipeline_status = data.get("object_attributes", {}).get("status")
        
        # Only process failed pipelines
        if pipeline_status not in ["failed", "success"]:
            return {"status": "ignored", "reason": f"Pipeline status: {pipeline_status}"}
        
        # Create session
        session_id = str(uuid.uuid4())
        session_data = {
            "session_id": session_id,
            "session_type": "pipeline",
            "project_id": str(data.get("project", {}).get("id")),
            "project_name": data.get("project", {}).get("name"),
            "pipeline_id": str(data.get("object_attributes", {}).get("id")),
            "pipeline_status": pipeline_status,
            "branch": data.get("object_attributes", {}).get("ref"),
            "subscription_id": subscription_id,
            "webhook_data": data,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(minutes=settings.session_timeout_minutes)
        }
        
        # Save to database
        await self.db.create_session(session_data)
        
        # Publish to queue for processing
        event_name = "pipeline_failed" if pipeline_status == "failed" else "pipeline_success"
        await self.queue_publisher.publish_event(
            event_type=event_name,
            session_id=session_id,
            data=session_data
        )
        
        log.info(f"Created session {session_id} for {event_name}")
        
        return {
            "status": "processing",
            "session_id": session_id,
            "message": f"Processing {event_name}"
        }
    
    async def process_sonarqube_webhook(
        self,
        data: Dict[str, Any],
        subscription_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process SonarQube webhook"""
        quality_gate = data.get("qualityGate", {})
        
        if quality_gate.get("status") != "ERROR":
            return {"status": "ignored", "reason": "Quality gate passed"}
        
        # Create session
        session_id = str(uuid.uuid4())
        session_data = {
            "session_id": session_id,
            "session_type": "quality",
            "project_id": data.get("project", {}).get("key"),
            "project_name": data.get("project", {}).get("name"),
            "subscription_id": subscription_id,
            "webhook_data": data,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(minutes=settings.session_timeout_minutes)
        }
        
        # Save to database
        await self.db.create_session(session_data)
        
        # Publish to queue
        await self.queue_publisher.publish_event(
            event_type="quality_failed",
            session_id=session_id,
            data=session_data
        )
        
        log.info(f"Created session {session_id} for quality gate failure")
        
        return {
            "status": "processing",
            "session_id": session_id,
            "message": "Processing quality gate failure"
        }