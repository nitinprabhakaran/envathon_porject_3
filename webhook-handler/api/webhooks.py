"""Simplified Webhook API - Just receives and forwards to queue"""
from fastapi import APIRouter, Request, HTTPException, Header, Depends
from typing import Dict, Any, Optional, List
import json
import uuid
import hmac
import hashlib
import re
from datetime import datetime, timedelta
from services.queue_publisher import QueuePublisher
from db.database import Database
from utils.logger import log
from config import settings

router = APIRouter(tags=["webhooks"])

def extract_session_from_branch(branch_name: str) -> Optional[str]:
    """Extract session ID from fix branch name using configured prefixes"""
    if not branch_name:
        return None
    
    # Get branch prefixes from environment (with defaults)
    pipeline_prefix = getattr(settings, 'BRANCH_PREFIX_PIPELINE', 'fix/pipeline_')
    quality_prefix = getattr(settings, 'BRANCH_PREFIX_QUALITY', 'fix/quality_')
    
    # Check for our session-based branch naming pattern: <prefix><session_id>_<timestamp>
    for prefix in [pipeline_prefix, quality_prefix]:
        if branch_name.startswith(prefix):
            # Extract the part after prefix
            suffix = branch_name[len(prefix):]
            # Look for session ID (32 chars without hyphens) followed by underscore and timestamp
            match = re.match(r'^([a-f0-9]{32})_\d{8}$', suffix)
            if match:
                # Convert back to UUID format with hyphens
                session_hex = match.group(1)
                session_id = f"{session_hex[:8]}-{session_hex[8:12]}-{session_hex[12:16]}-{session_hex[16:20]}-{session_hex[20:32]}"
                return session_id
    
    return None

def find_session_by_branch(branch_name: str, active_sessions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find active session that matches the branch name"""
    session_id = extract_session_from_branch(branch_name)
    if not session_id:
        return None
    
    # Find session with matching ID
    for session in active_sessions:
        if session.get("id") == session_id:
            return session
    
    return None

async def is_fix_branch_event(data: Dict[str, Any], db: Database) -> Optional[Dict[str, Any]]:
    """
    Determine if this webhook event is related to a fix branch and find the corresponding session.
    Returns session info if this is a fix branch event, None otherwise.
    """
    try:
        # Extract branch name based on event type
        branch_name = None
        
        # For pipeline events
        if "object_attributes" in data and "ref" in data["object_attributes"]:
            branch_name = data["object_attributes"]["ref"]
        
        # For merge request events
        elif "object_attributes" in data and "source_branch" in data["object_attributes"]:
            branch_name = data["object_attributes"]["source_branch"]
        
        if not branch_name:
            return None
        
        # Check if this looks like a fix branch
        session_short = extract_session_from_branch(branch_name)
        if not session_short:
            return None
        
        # Get active sessions for this project
        project_id = str(data.get("project", {}).get("id", ""))
        active_sessions = await db.get_active_sessions_for_project(project_id)
        
        # Find matching session
        matching_session = find_session_by_branch(branch_name, active_sessions)
        
        if matching_session:
            log.info(f"Fix branch detected: {branch_name} -> session {matching_session['id']}")
            return {
                "session": matching_session,
                "branch_name": branch_name,
                "session_short": session_short,
                "is_fix_branch": True
            }
        else:
            log.info(f"Fix branch pattern detected but no active session found: {branch_name}")
            
        return None
        
    except Exception as e:
        log.error(f"Error checking fix branch event: {e}")
        return None

async def should_process_pipeline_event(data: Dict[str, Any], db: Database) -> Dict[str, Any]:
    """
    Determine if pipeline event should be processed and how.
    Returns processing decision with context.
    """
    pipeline_status = data.get("object_attributes", {}).get("status")
    project_id = str(data.get("project", {}).get("id"))
    branch_name = data.get("object_attributes", {}).get("ref", "")
    
    # Check if this is a fix branch
    fix_branch_info = await is_fix_branch_event(data, db)
    
    if fix_branch_info:
        # This is a fix branch - only process success/failure outcomes
        if pipeline_status in ["success", "failed"]:
            return {
                "should_process": True,
                "processing_type": "fix_branch_result",
                "session_id": fix_branch_info["session"]["id"],
                "original_session": fix_branch_info["session"],
                "branch_name": branch_name,
                "reason": f"Fix branch {pipeline_status} for active session"
            }
        else:
            return {
                "should_process": False,
                "processing_type": "fix_branch_ignored",
                "reason": f"Fix branch pipeline status '{pipeline_status}' not final"
            }
    else:
        # Regular branch - only process failures for new analysis
        if pipeline_status == "failed":
            return {
                "should_process": True,
                "processing_type": "new_failure_analysis",
                "reason": "New pipeline failure requiring analysis"
            }
        else:
            return {
                "should_process": False,
                "processing_type": "regular_success_ignored",
                "reason": f"Regular pipeline status '{pipeline_status}' not requiring analysis"
            }

async def should_process_mr_event(data: Dict[str, Any], db: Database) -> Dict[str, Any]:
    """
    Determine if merge request event should be processed and how.
    Returns processing decision with context.
    """
    mr_action = data.get("object_attributes", {}).get("action", "")
    mr_state = data.get("object_attributes", {}).get("state", "")
    source_branch = data.get("object_attributes", {}).get("source_branch", "")
    
    # Check if this is a fix branch MR
    fix_branch_info = await is_fix_branch_event(data, db)
    
    if fix_branch_info:
        # This is a fix branch MR - track important state changes
        if mr_action in ["merge", "close"] or (mr_action == "update" and mr_state in ["merged", "closed"]):
            return {
                "should_process": True,
                "processing_type": "fix_branch_mr_result",
                "session_id": fix_branch_info["session"]["id"],
                "original_session": fix_branch_info["session"],
                "branch_name": source_branch,
                "reason": f"Fix branch MR {mr_action} for active session"
            }
        else:
            return {
                "should_process": False,
                "processing_type": "fix_branch_mr_ignored",
                "reason": f"Fix branch MR action '{mr_action}' not requiring tracking"
            }
    else:
        # Regular MR - generally not processed unless specifically needed
        return {
            "should_process": False,
            "processing_type": "regular_mr_ignored",
            "reason": "Regular MR not related to active fix sessions"
        }

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
    """Handle GitLab pipeline webhook events with smart filtering"""
    project_id = str(data.get("project", {}).get("id"))
    pipeline_id = str(data.get("object_attributes", {}).get("id"))
    pipeline_status = data.get("object_attributes", {}).get("status")
    branch_name = data.get("object_attributes", {}).get("ref", "")
    
    log.info(f"Pipeline {pipeline_id} on branch '{branch_name}' status: {pipeline_status}")
    
    # Smart processing decision
    processing_decision = await should_process_pipeline_event(data, db)
    
    if not processing_decision["should_process"]:
        log.info(f"Ignoring pipeline event: {processing_decision['reason']}")
        return {
            "status": "ignored",
            "reason": processing_decision["reason"],
            "processing_type": processing_decision["processing_type"]
        }
    
    # Handle based on processing type
    if processing_decision["processing_type"] == "fix_branch_result":
        return await handle_fix_branch_pipeline_result(data, db, processing_decision)
    elif processing_decision["processing_type"] == "new_failure_analysis":
        return await handle_new_pipeline_failure(data, db)
    else:
        return {"status": "error", "reason": "Unknown processing type"}

async def handle_fix_branch_pipeline_result(data: Dict[str, Any], db: Database, decision: Dict[str, Any]) -> Dict[str, Any]:
    """Handle pipeline results for fix branches"""
    session_id = decision["session_id"]
    original_session = decision["original_session"]
    branch_name = decision["branch_name"]
    pipeline_status = data.get("object_attributes", {}).get("status")
    pipeline_id = str(data.get("object_attributes", {}).get("id"))
    
    log.info(f"Processing fix branch pipeline result: {pipeline_status} for session {session_id}")
    
    # Create event for strands-agent to track fix attempt result
    message = {
        "event_type": f"fix_branch_pipeline_{pipeline_status}",
        "session_id": session_id,
        "project_id": str(data.get("project", {}).get("id")),
        "branch_name": branch_name,
        "pipeline_id": pipeline_id,
        "pipeline_status": pipeline_status,
        "original_session_type": original_session.get("session_type"),
        "webhook_data": data,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Send to strands-agent for session update
    queue_instance = get_queue_publisher()
    await queue_instance.connect()
    await queue_instance.publish_event(f"fix_branch_pipeline_{pipeline_status}", session_id, message)
    
    log.info(f"Published fix branch pipeline {pipeline_status} event for session {session_id}")
    
    return {
        "status": "processed",
        "session_id": session_id,
        "pipeline_status": pipeline_status,
        "processing_type": "fix_branch_result"
    }

async def handle_new_pipeline_failure(data: Dict[str, Any], db: Database) -> Dict[str, Any]:
    """Handle new pipeline failures that need analysis"""
    pipeline_status = data.get("object_attributes", {}).get("status")
    project_id = str(data.get("project", {}).get("id"))
    pipeline_id = str(data.get("object_attributes", {}).get("id"))
    
    # Check for existing session with same pipeline ID to avoid duplicates
    existing_session = await db.find_session_by_unique_id("pipeline", project_id, pipeline_id)
    
    if existing_session:
        session_id = existing_session["id"]
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
            "id": session_id,
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
        
        # Extract failed job info
        failed_jobs = [job for job in data.get("builds", []) if job.get("status") == "failed"]
        if failed_jobs:
            failed_jobs.sort(key=lambda x: x.get("finished_at", ""), reverse=True)
            first_failed = failed_jobs[0]
            session_data["job_name"] = first_failed.get("name")
            session_data["failed_stage"] = first_failed.get("stage")

        # Store new session
        await db.create_session(session_data)
        log.info(f"Created new session {session_id} for pipeline {pipeline_id}")

    # Determine event type based on failure analysis
    is_quality_failure = detect_quality_failure_from_pipeline(data)
    event_type = "pipeline_failed"
    
    # Send to strands-agent for analysis
    message = {
        "event_type": event_type,
        "session_id": session_id,
        "project_id": project_id,
        "pipeline_status": pipeline_status,
        "webhook_data": data,
        "quality_failure_detected": is_quality_failure,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    queue_instance = get_queue_publisher()
    await queue_instance.connect()
    await queue_instance.publish_event(event_type, session_id, message)
    
    log.info(f"Created session {session_id} and published to queue for analysis")
    
    return {
        "status": "processed",
        "session_id": session_id,
        "pipeline_id": pipeline_id,
        "processing_type": "new_failure_analysis"
    }
    
    return {
        "status": "queued",
        "session_id": session_id,
        "message": "Event queued for processing"
    }

async def handle_merge_request_webhook(data: Dict[str, Any], db: Database) -> Dict[str, Any]:
    """Handle GitLab merge request webhook events with smart filtering"""
    mr_attributes = data.get("object_attributes", {})
    mr_action = mr_attributes.get("action")
    mr_state = mr_attributes.get("state")
    project_id = str(data.get("project", {}).get("id"))
    mr_iid = str(mr_attributes.get("iid"))
    source_branch = mr_attributes.get("source_branch", "")
    
    log.info(f"Received MR webhook: action={mr_action}, state={mr_state}, project={project_id}, MR !{mr_iid}, branch={source_branch}")
    
    # Smart processing decision
    processing_decision = await should_process_mr_event(data, db)
    
    if not processing_decision["should_process"]:
        log.info(f"Ignoring MR event: {processing_decision['reason']}")
        return {
            "status": "ignored",
            "reason": processing_decision["reason"],
            "processing_type": processing_decision["processing_type"]
        }
    
    # Handle fix branch MR results
    if processing_decision["processing_type"] == "fix_branch_mr_result":
        return await handle_fix_branch_mr_result(data, db, processing_decision)
    else:
        return {"status": "error", "reason": "Unknown processing type"}

async def handle_fix_branch_mr_result(data: Dict[str, Any], db: Database, decision: Dict[str, Any]) -> Dict[str, Any]:
    """Handle merge request results for fix branches"""
    session_id = decision["session_id"]
    original_session = decision["original_session"]
    branch_name = decision["branch_name"]
    mr_action = data.get("object_attributes", {}).get("action", "")
    mr_state = data.get("object_attributes", {}).get("state", "")
    mr_iid = data.get("object_attributes", {}).get("iid")
    
    log.info(f"Processing fix branch MR result: {mr_action}/{mr_state} for session {session_id}")
    
    # Determine the outcome
    if mr_action == "merge" or mr_state == "merged":
        outcome = "merged"
    elif mr_action == "close" or mr_state == "closed":
        outcome = "closed"
    else:
        outcome = "updated"
    
    # Create event for strands-agent to track fix attempt result
    message = {
        "event_type": f"fix_branch_mr_{outcome}",
        "session_id": session_id,
        "project_id": str(data.get("project", {}).get("id")),
        "branch_name": branch_name,
        "mr_iid": mr_iid,
        "mr_action": mr_action,
        "mr_state": mr_state,
        "outcome": outcome,
        "original_session_type": original_session.get("session_type"),
        "webhook_data": data,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Send to strands-agent for session update
    queue_instance = get_queue_publisher()
    await queue_instance.connect()
    await queue_instance.publish_event(f"fix_branch_mr_{outcome}", session_id, message)
    
    log.info(f"Published fix branch MR {outcome} event for session {session_id}")
    
    return {
        "status": "processed",
        "session_id": session_id,
        "mr_iid": mr_iid,
        "outcome": outcome,
        "processing_type": "fix_branch_mr_result"
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