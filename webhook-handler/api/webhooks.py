"""Simplified Webhook API - Just receives and forwards to queue"""
from fastapi import APIRouter, Request, HTTPException, Header, Depends
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

router = APIRouter(tags=["webhooks"])

# Global instances - will be initialized in main.py lifespan
queue_publisher = None

def get_queue_publisher():
    """Get or create queue publisher"""
    global queue_publisher
    if queue_publisher is None:
        queue_publisher = QueuePublisher()
    return queue_publisher

def get_database() -> Database:
    """Get database instance from application state"""
    from main import app_state
    if not app_state.db:
        raise HTTPException(status_code=503, detail="Database not available")
    return app_state.db

async def verify_webhook_auth(
    project_data: Dict[str, Any],
    x_gitlab_token: Optional[str] = None,
    x_sonarqube_webhook_secret: Optional[str] = None,
    db: Database = None
) -> bool:
    """Verify webhook authentication against subscription-specific secrets"""
    if not settings.webhook_auth_enabled:
        return True
    
    log.info(f"Webhook auth check: gitlab_token={'present' if x_gitlab_token else 'missing'}, sonar_secret={'present' if x_sonarqube_webhook_secret else 'missing'}")
    
    # Try GitLab authentication
    if x_gitlab_token and project_data.get("project", {}).get("id"):
        project_id = str(project_data.get("project", {}).get("id"))
        log.info(f"GitLab auth: Looking for subscription with project_id={project_id}")
        
        subscription = await db.find_subscription_by_project(
            project_id=project_id,
            project_type="gitlab",
            status="active"
        )
        
        if subscription:
            log.info(f"GitLab auth: Found subscription {subscription.get('subscription_id')}")
            if subscription.get("webhook_secret"):
                log.info(f"GitLab auth: Comparing secrets (header length: {len(x_gitlab_token)}, stored length: {len(subscription['webhook_secret'])})")
                if hmac.compare_digest(x_gitlab_token, subscription["webhook_secret"]):
                    log.info("GitLab auth: Secret comparison successful")
                    return True
                else:
                    log.warning("GitLab auth: Secret comparison failed")
            else:
                log.warning("GitLab auth: No webhook_secret in subscription")
        else:
            log.warning(f"GitLab auth: No subscription found for project {project_id}")
    elif x_gitlab_token:
        log.warning(f"GitLab auth: Missing project ID in data: {project_data.get('project', {})}")
    else:
        log.info("GitLab auth: No X-Gitlab-Token header")
    
    # Try SonarQube authentication
    if x_sonarqube_webhook_secret and project_data.get("project", {}).get("key"):
        project_key = project_data.get("project", {}).get("key")
        log.info(f"SonarQube auth: Looking for subscription with project_id={project_key}")
        
        subscription = await db.find_subscription_by_project(
            project_id=project_key,
            project_type="sonarqube", 
            status="active"
        )
        
        if subscription:
            log.info(f"SonarQube auth: Found subscription {subscription.get('subscription_id')}")
            if subscription.get("webhook_secret"):
                log.info(f"SonarQube auth: Comparing secrets (header length: {len(x_sonarqube_webhook_secret)}, stored length: {len(subscription['webhook_secret'])})")
                if hmac.compare_digest(x_sonarqube_webhook_secret, subscription["webhook_secret"]):
                    log.info("SonarQube auth: Secret comparison successful")
                    return True
                else:
                    log.warning("SonarQube auth: Secret comparison failed")
            else:
                log.warning("SonarQube auth: No webhook_secret in subscription")
        else:
            log.warning(f"SonarQube auth: No subscription found for project {project_key}")
    elif x_sonarqube_webhook_secret:
        log.warning(f"SonarQube auth: Missing project key in data: {project_data.get('project', {})}")
    else:
        log.info("SonarQube auth: No X-Sonarqube-Webhook-Secret header")
    
    # Fallback to global secrets for backwards compatibility
    if x_gitlab_token and settings.gitlab_webhook_secret:
        log.info("GitLab auth: Trying global secret fallback")
        if hmac.compare_digest(x_gitlab_token, settings.gitlab_webhook_secret):
            log.info("GitLab auth: Global secret comparison successful")
            return True
    
    if x_sonarqube_webhook_secret and settings.sonarqube_webhook_secret:
        log.info("SonarQube auth: Trying global secret fallback")
        if hmac.compare_digest(x_sonarqube_webhook_secret, settings.sonarqube_webhook_secret):
            log.info("SonarQube auth: Global secret comparison successful")
            return True
    
    log.warning("Webhook auth: All authentication methods failed")
    return False

@router.post("/gitlab")
async def handle_gitlab_webhook(
    request: Request,
    x_gitlab_token: Optional[str] = Header(None, alias="X-Gitlab-Token"),
    db: Database = Depends(get_database)
):
    """Receive GitLab webhook and forward to queue"""
    try:
        data = await request.json()
        
        # Verify authentication with project data
        if not await verify_webhook_auth(
            project_data=data,
            x_gitlab_token=x_gitlab_token,
            db=db
        ):
            raise HTTPException(status_code=401, detail="Invalid webhook authentication")
        
        log.info(f"Received GitLab webhook: {data.get('object_kind', 'unknown')}")
        
        # Basic validation
        if data.get("object_kind") != "pipeline":
            return {"status": "ignored", "reason": "Not a pipeline event"}
        
        pipeline_status = data.get("object_attributes", {}).get("status")
        project_id = str(data.get("project", {}).get("id"))
        
        # Only process failed pipelines for immediate analysis
        if pipeline_status != "failed":
            log.info(f"Ignoring pipeline with status: {pipeline_status}")
            return {"status": "ignored", "reason": f"Pipeline status: {pipeline_status}"}

        # Check for existing session with same pipeline ID to avoid duplicates
        pipeline_id = str(data.get("object_attributes", {}).get("id"))
        existing_session = await db.find_session_by_unique_id("pipeline", project_id, pipeline_id)
        
        if existing_session:
            session_id = existing_session["id"]  # Use 'id' column name
            log.info(f"Found existing session {session_id} for pipeline {pipeline_id}, updating...")
            
            # Update existing session with latest data
            await db.update_session(session_id, {
                "pipeline_status": pipeline_status,
                "updated_at": datetime.utcnow(),
                "webhook_data": data
            })
        else:
            # Create new session for new pipeline failure
            session_id = str(uuid.uuid4())
            session_data = {
                "id": session_id,  # Use 'id' column name
                "session_type": "pipeline",
                "project_id": project_id,
                "project_name": data.get("project", {}).get("name"),
                "pipeline_id": pipeline_id,
                "pipeline_url": data.get("object_attributes", {}).get("url"),
                "pipeline_status": pipeline_status,
                "branch": data.get("object_attributes", {}).get("ref"),
                "commit_sha": data.get("object_attributes", {}).get("sha"),
                "status": "active",
                "created_at": datetime.utcnow(),
                "expires_at": datetime.utcnow() + timedelta(minutes=settings.session_timeout_minutes),
                "webhook_data": data
            }        # Extract failed job info if failure
        if pipeline_status == "failed":
            failed_jobs = [job for job in data.get("builds", []) if job.get("status") == "failed"]
            if failed_jobs:
                failed_jobs.sort(key=lambda x: x.get("finished_at", ""), reverse=True)
                first_failed = failed_jobs[0]
                session_data["job_name"] = first_failed.get("name")
                session_data["failed_stage"] = first_failed.get("stage")

            # Store new session
            await db.create_session(session_data)
            log.info(f"Created new session {session_id} for pipeline {pipeline_id}")

        # Only failed pipelines reach here, so event type is always pipeline_failed
        event_type = "pipeline_failed"
        
        # Publish to queue for agent to process
        message = {
            "event_type": event_type,
            "session_id": session_id,
            "project_id": project_id,
            "pipeline_status": pipeline_status,
            "webhook_data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        queue_instance = get_queue_publisher()
        await queue_instance.connect()
        await queue_instance.publish_event(event_type, session_id, message)
        
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
    x_sonarqube_webhook_secret: Optional[str] = Header(None, alias="X-Sonarqube-Webhook-Secret"),
    db: Database = Depends(get_database)
):
    """Receive SonarQube webhook and forward to queue"""
    try:
        data = await request.json()
        
        # Verify authentication with project data
        if not await verify_webhook_auth(
            project_data=data,
            x_sonarqube_webhook_secret=x_sonarqube_webhook_secret,
            db=db
        ):
            raise HTTPException(status_code=401, detail="Invalid webhook authentication")
        
        log.info(f"Received SonarQube webhook for project {data.get('project', {}).get('key', 'unknown')}")
        
        quality_gate = data.get("qualityGate", {})
        if quality_gate.get("status") != "ERROR":
            return {"status": "ignored", "reason": "Quality gate passed"}

        project = data.get("project", {})
        project_key = project.get("key")
        branch_name = data.get("branch", {}).get("name", "main")
        
        # Check for existing session to avoid duplicates
        # Use combination of project key + branch for SonarQube uniqueness
        unique_id = f"{project_key}:{branch_name}"
        existing_session = await db.find_session_by_unique_id("quality", project_key, unique_id)
        
        if existing_session:
            session_id = existing_session["id"]  # Use 'id' column name
            log.info(f"Found existing session {session_id} for SonarQube project {project_key}:{branch_name}, updating...")
            
            # Update existing session with latest data
            await db.update_session(session_id, {
                "quality_gate_status": quality_gate.get("status"),
                "updated_at": datetime.utcnow(),
                "webhook_data": data
            })
        else:
            # Create new session for new quality gate failure
            session_id = str(uuid.uuid4())
            session_data = {
                "id": session_id,  # Use 'id' column name
                "session_type": "quality",
                "project_id": project_key,  # Use SonarQube project key as project_id
                "project_name": project.get("name"),
                "sonarqube_key": project_key,
                "unique_id": unique_id,  # Store unique identifier
                "quality_gate_status": quality_gate.get("status"),
                "branch": branch_name,
                "status": "active",
                "created_at": datetime.utcnow(),
                "expires_at": datetime.utcnow() + timedelta(minutes=settings.session_timeout_minutes),
                "webhook_data": data
            }

            # Store new session
            await db.create_session(session_data)
            log.info(f"Created new session {session_id} for SonarQube project {project_key}:{branch_name}")

        # SonarQube quality gate failure maps to quality_failed event
        event_type = "quality_failed"
        
        # Publish to queue for agent to process
        message = {
            "event_type": event_type,
            "session_id": session_id,
            "sonarqube_key": project_key,
            "quality_gate_status": quality_gate.get("status"),
            "webhook_data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        queue_instance = get_queue_publisher()
        await queue_instance.connect()
        await queue_instance.publish_event(event_type, session_id, message)
        
        log.info(f"Created session {session_id} and published to queue")
        
        return {
            "status": "queued",
            "session_id": session_id,
            "message": "Event queued for processing"
        }
        
    except Exception as e:
        log.error(f"Failed to process SonarQube webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))