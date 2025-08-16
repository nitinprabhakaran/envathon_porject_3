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

async def detect_quality_failure_from_pipeline(data: Dict[str, Any]) -> bool:
    """Detect if pipeline failure is due to quality gate failure"""
    failed_jobs = [job for job in data.get("builds", []) if job.get("status") == "failed"]
    
    if not failed_jobs:
        return False
    
    # Sort by finished_at to get the most recent failure
    failed_jobs.sort(key=lambda x: x.get("finished_at", ""), reverse=True)
    most_recent_failed_job = failed_jobs[0]
    
    job_name = most_recent_failed_job.get("name", "").lower()
    
    # Check if it's a quality/sonar related job
    quality_keywords = ['sonar', 'quality', 'scan', 'analysis', 'gate']
    if any(keyword in job_name for keyword in quality_keywords):
        log.info(f"Detected quality failure from job name: {job_name}")
        return True
    
    # Could also check job logs here if needed, but for now use job name detection
    return False

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

async def handle_pipeline_webhook(data: Dict[str, Any], db: Database) -> Dict[str, Any]:
    """Handle GitLab pipeline webhook events"""
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
        }
        
        # Extract failed job info if failure
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

    # Determine if this is a quality failure by checking job names
    if detect_quality_failure_from_pipeline(data):
        event_type = "quality_failed"
        log.info(f"Detected quality failure in pipeline {pipeline_id}")
    else:
        event_type = "pipeline_failed"
        log.info(f"Detected pipeline failure in pipeline {pipeline_id}")
    
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

async def handle_merge_request_webhook(data: Dict[str, Any], db: Database) -> Dict[str, Any]:
    """Handle GitLab merge request webhook events"""
    mr_attributes = data.get("object_attributes", {})
    mr_action = mr_attributes.get("action")
    mr_state = mr_attributes.get("state")
    project_id = str(data.get("project", {}).get("id"))
    mr_iid = str(mr_attributes.get("iid"))
    
    log.info(f"Received MR webhook: action={mr_action}, state={mr_state}, project={project_id}, MR !{mr_iid}")
    
    # Handle merge request events that we care about
    if mr_action in ["open", "update", "merge", "close"]:
        # Publish merge request event to queue for potential processing by strands-agent
        message = {
            "event_type": "merge_request_" + mr_action,
            "project_id": project_id,
            "mr_iid": mr_iid,
            "mr_action": mr_action,
            "mr_state": mr_state,
            "webhook_data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        queue_instance = get_queue_publisher()
        await queue_instance.connect()
        await queue_instance.publish_event(f"merge_request_{mr_action}", f"mr_{project_id}_{mr_iid}", message)
        
        log.info(f"Published MR event to queue: {mr_action} for MR !{mr_iid}")
        
        return {
            "status": "queued",
            "mr_iid": mr_iid,
            "action": mr_action,
            "message": f"MR {mr_action} event queued for processing"
        }
    else:
        return {
            "status": "ignored",
            "reason": f"MR action '{mr_action}' not tracked"
        }

def detect_quality_failure_from_pipeline(data: Dict[str, Any]) -> bool:
    """Detect if pipeline failure is due to quality issues by analyzing job names"""
    failed_jobs = [job for job in data.get("builds", []) if job.get("status") == "failed"]
    
    quality_keywords = ['sonar', 'quality', 'scan', 'analysis', 'gate', 'code-quality', 'lint', 'security']
    
    for job in failed_jobs:
        job_name = job.get("name", "").lower()
        if any(keyword in job_name for keyword in quality_keywords):
            return True
    
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
        
        object_kind = data.get("object_kind")
        
        # Handle different GitLab webhook types
        if object_kind == "pipeline":
            return await handle_pipeline_webhook(data, db)
        elif object_kind == "merge_request":
            return await handle_merge_request_webhook(data, db)
        else:
            return {"status": "ignored", "reason": f"Unsupported event type: {object_kind}"}
        
    except Exception as e:
        log.error(f"Failed to process GitLab webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# SonarQube webhook endpoint removed - quality detection done in GitLab pipeline analysis