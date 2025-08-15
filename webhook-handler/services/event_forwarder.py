"""Simplified Event Forwarder for Webhook Handler"""
import json
import uuid
import boto3
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from utils.logger import log
from config import settings
from db.database import Database

class EventForwarder:
    """Forward webhook events to Strands Agent via SQS"""
    
    def __init__(self):
        self.db = Database()
        self.sqs = boto3.client('sqs', region_name=settings.aws_region)
        self.queue_url = settings.sqs_queue_url
        
    async def process_gitlab_webhook(
        self,
        data: Dict[str, Any],
        subscription_id: Optional[str] = None,
        webhook_secret: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process and forward GitLab webhook"""
        try:
            event_type = data.get("object_kind")
            if event_type != "pipeline":
                return {"status": "ignored", "reason": "Not a pipeline event"}
            
            pipeline_status = data.get("object_attributes", {}).get("status")
            project_id = str(data.get("project", {}).get("id"))
            
            # Create session
            session_id = str(uuid.uuid4())
            session_data = {
                "session_id": session_id,
                "session_type": "pipeline",  # Initial type, agent will determine if quality
                "project_id": project_id,
                "project_name": data.get("project", {}).get("name"),
                "pipeline_id": str(data.get("object_attributes", {}).get("id")),
                "pipeline_status": pipeline_status,
                "branch": data.get("object_attributes", {}).get("ref"),
                "subscription_id": subscription_id,
                "created_at": datetime.utcnow(),
                "expires_at": datetime.utcnow() + timedelta(minutes=settings.session_timeout_minutes)
            }
            
            # Store minimal session data
            await self.db.create_session(session_data)
            
            # Forward to SQS
            message = {
                "event_type": "gitlab_pipeline",
                "session_id": session_id,
                "project_id": project_id,
                "pipeline_status": pipeline_status,
                "webhook_data": data,
                "subscription_id": subscription_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            self.sqs.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(message),
                MessageAttributes={
                    'event_type': {'StringValue': 'gitlab_pipeline', 'DataType': 'String'},
                    'session_id': {'StringValue': session_id, 'DataType': 'String'}
                }
            )
            
            log.info(f"Forwarded GitLab event to queue: session={session_id}")
            
            return {
                "status": "queued",
                "session_id": session_id,
                "queue_message_id": message.get("MessageId")
            }
            
        except Exception as e:
            log.error(f"Failed to process GitLab webhook: {e}")
            return {"status": "error", "error": str(e)}
    
    async def process_sonarqube_webhook(
        self,
        data: Dict[str, Any],
        subscription_id: Optional[str] = None,
        webhook_secret: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process and forward SonarQube webhook"""
        try:
            quality_gate = data.get("qualityGate", {})
            if quality_gate.get("status") != "ERROR":
                return {"status": "ignored", "reason": "Quality gate passed"}
            
            project = data.get("project", {})
            
            # Create session
            session_id = str(uuid.uuid4())
            session_data = {
                "session_id": session_id,
                "session_type": "quality",
                "sonarqube_key": project.get("key"),
                "project_name": project.get("name"),
                "quality_gate_status": quality_gate.get("status"),
                "subscription_id": subscription_id,
                "created_at": datetime.utcnow(),
                "expires_at": datetime.utcnow() + timedelta(minutes=settings.session_timeout_minutes)
            }
            
            # Store minimal session data
            await self.db.create_session(session_data)
            
            # Forward to SQS
            message = {
                "event_type": "sonarqube_quality",
                "session_id": session_id,
                "sonarqube_key": project.get("key"),
                "quality_gate_status": quality_gate.get("status"),
                "webhook_data": data,
                "subscription_id": subscription_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            self.sqs.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(message),
                MessageAttributes={
                    'event_type': {'StringValue': 'sonarqube_quality', 'DataType': 'String'},
                    'session_id': {'StringValue': session_id, 'DataType': 'String'}
                }
            )
            
            log.info(f"Forwarded SonarQube event to queue: session={session_id}")
            
            return {
                "status": "queued",
                "session_id": session_id,
                "queue_message_id": message.get("MessageId")
            }
            
        except Exception as e:
            log.error(f"Failed to process SonarQube webhook: {e}")
            return {"status": "error", "error": str(e)}