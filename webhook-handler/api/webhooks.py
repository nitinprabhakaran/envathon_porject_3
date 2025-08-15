"""Simplified Webhook API - Just receives and forwards to queue"""
from fastapi import APIRouter, Request, HTTPException, Header
from typing import Dict, Any, Optional
import json
import uuid
import hmac
import hashlib
from datetime import datetime, timedelta
from services.queue_publisher import QueuePublisher
from db.database import Database
from utils.logger import log
from config import settings

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

queue_publisher = QueuePublisher()
db = Database()

async def verify_webhook_auth(
    x_gitlab_token: Optional[str] = Header(None),
    x_sonarqube_webhook_secret: Optional[str] = Header(None)
) -> bool:
    """Verify webhook authentication"""
    if not settings.webhook_auth_enabled:
        return True
    
    if x_gitlab_token and hmac.compare_digest(x_gitlab_token, settings.gitlab_webhook_secret):
        return True
    
    if x_sonarqube_webhook_secret and hmac.compare_digest(x_sonarqube_webhook_secret, settings.sonarqube_webhook_secret):
        return True
    
    raise HTTPException(status_code=401, detail="Invalid webhook authentication")

@router.post("/gitlab")
async def handle_gitlab_webhook(
    request: Request,
    x_gitlab_token: Optional[str] = Header(None)
):
    """Receive GitLab webhook and forward to queue"""
    await verify_webhook_auth(x_gitlab_token=x_gitlab_token)
    
    try:
        data = await request.json()
        log.info(f"Received GitLab webhook: {data.get('object_kind')}")
        
        # Basic validation
        if data.get("object_kind") != "pipeline":
            return {"status": "ignored", "reason": "Not a pipeline event"}
        
        pipeline_status = data.get("object_attributes", {}).get("status")
        project_id = str(data.get("project", {}).get("id"))
        
        # Create minimal session
        session_id = str(uuid.uuid4())
        session_data = {
            "id": session_id,
            "session_type": "pipeline",  # Will be determined by agent
            "project_id": project_id,
            "project_name": data.get("project", {}).get("name"),
            "pipeline_id": str(data.get("object_attributes", {}).get("id")),
            "pipeline_url": data.get("object_attributes", {}).get("url"),
            "pipeline_status": pipeline_status,
            "branch": data.get("object_attributes", {}).get("ref"),
            "commit_sha": data.get("object_attributes", {}).get("sha"),
            "status": "active",
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(minutes=settings.session_timeout_minutes)
        }
        
        # Extract failed job info if failure
        if pipeline_status == "failed":
            failed_jobs = [job for job in data.get("builds", []) if job.get("status") == "failed"]
            if failed_jobs:
                failed_jobs.sort(key=lambda x: x.get("finished_at", ""), reverse=True)
                first_failed = failed_jobs[0]
                session_data["job_name"] = first_failed.get("name")
                session_data["failed_stage"] = first_failed.get("stage")
        
        # Store minimal session
        await db.create_session(session_data)
        
        # Publish to queue for agent to process
        message = {
            "event_type": "gitlab_pipeline",
            "session_id": session_id,
            "project_id": project_id,
            "pipeline_status": pipeline_status,
            "webhook_data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await queue_publisher.publish(message)
        
        log.info(f"Created session {session_id} and published to queue")
        
        return {
            "status": "queued",
            "session_id": session_id,
            "message": "Event queued for processing"
        }
        
    except Exception as e:
        log.error(f"Failed to process GitLab webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/sonarqube")
async def handle_sonarqube_webhook(
    request: Request,
    x_sonarqube_webhook_secret: Optional[str] = Header(None)
):
    """Receive SonarQube webhook and forward to queue"""
    await verify_webhook_auth(x_sonarqube_webhook_secret=x_sonarqube_webhook_secret)
    
    try:
        data = await request.json()
        log.info(f"Received SonarQube webhook for project {data.get('project', {}).get('key')}")
        
        quality_gate = data.get("qualityGate", {})
        if quality_gate.get("status") != "ERROR":
            return {"status": "ignored", "reason": "Quality gate passed"}
        
        project = data.get("project", {})
        
        # Create minimal session
        session_id = str(uuid.uuid4())
        session_data = {
            "id": session_id,
            "session_type": "quality",
            "sonarqube_key": project.get("key"),
            "project_name": project.get("name"),
            "quality_gate_status": quality_gate.get("status"),
            "branch": data.get("branch", {}).get("name", "main"),
            "status": "active",
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(minutes=settings.session_timeout_minutes)
        }
        
        # Store minimal session
        await db.create_session(session_data)
        
        # Publish to queue for agent to process
        message = {
            "event_type": "sonarqube_quality",
            "session_id": session_id,
            "sonarqube_key": project.get("key"),
            "quality_gate_status": quality_gate.get("status"),
            "webhook_data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        await queue_publisher.publish(message)
        
        log.info(f"Created session {session_id} and published to queue")
        
        return {
            "status": "queued",
            "session_id": session_id,
            "message": "Event queued for processing"
        }
        
    except Exception as e:
        log.error(f"Failed to process SonarQube webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))