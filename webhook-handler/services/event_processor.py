"""Event Processor for webhook events"""
import json
import uuid
import sys
import os
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from utils.logger import log
from config import settings
from db.database import Database
from services.queue_publisher import QueuePublisher

# Import local branch naming utilities
from utils.branch_naming import (
    safe_extract_session_id, 
    is_fix_branch, 
    get_branch_type,
    extract_branch_info
)

# Import fix iteration handler with proper path handling
fix_iteration_handler_available = False
try:
    # Try to import from strands-agent services
    strands_agent_path = os.path.join(os.path.dirname(__file__), '..', '..', 'strands-agent')
    if strands_agent_path not in sys.path:
        sys.path.append(strands_agent_path)
    
    from services.fix_iteration_handler import FixIterationHandler
    fix_iteration_handler_available = True
    log.info("FixIterationHandler imported successfully")
except ImportError as e:
    log.warning(f"Could not import FixIterationHandler: {e} - fix iteration features may not work")
    FixIterationHandler = None

class EventProcessor:
    """Process incoming webhook events"""
    
    def __init__(self):
        self.db = Database()
        self.queue_publisher = QueuePublisher()
        self.fix_iteration_handler = FixIterationHandler() if fix_iteration_handler_available else None
    
    async def process_gitlab_webhook(
        self,
        data: Dict[str, Any],
        subscription_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process GitLab webhook and create session"""
        event_type = data.get("object_kind")
        
        if event_type == "pipeline":
            return await self._process_pipeline_event(data, subscription_id)
        elif event_type == "push":
            return await self._process_push_event(data, subscription_id)
        else:
            return {"status": "ignored", "reason": f"Unsupported event type: {event_type}"}
    
    async def _process_pipeline_event(
        self,
        data: Dict[str, Any],
        subscription_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process pipeline events"""
        pipeline_status = data.get("object_attributes", {}).get("status")
        branch_name = data.get("object_attributes", {}).get("ref")
        
        # Check if this is a fix branch
        if is_fix_branch(branch_name):
            return await self._process_fix_branch_pipeline(data, subscription_id, branch_name)
        
        # Only process failed pipelines for new sessions
        if pipeline_status not in ["failed", "success"]:
            return {"status": "ignored", "reason": f"Pipeline status: {pipeline_status}"}
        
        # For non-fix branches, only create sessions for failures
        if pipeline_status == "success":
            return {"status": "ignored", "reason": "Success on non-fix branch"}
        
        # Create session for failed pipeline
        session_id = str(uuid.uuid4())
        session_data = {
            "session_id": session_id,
            "session_type": "pipeline",
            "project_id": str(data.get("project", {}).get("id")),
            "project_name": data.get("project", {}).get("name"),
            "pipeline_id": str(data.get("object_attributes", {}).get("id")),
            "pipeline_status": pipeline_status,
            "branch": branch_name,
            "subscription_id": subscription_id,
            "webhook_data": data,
            "created_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(minutes=settings.session_timeout_minutes)
        }
        
        # Save to database
        await self.db.create_session(session_data)
        
        # Publish to queue for processing
        await self.queue_publisher.publish_event(
            event_type="pipeline_failed",
            session_id=session_id,
            data=session_data
        )
        
        log.info(f"Created session {session_id} for pipeline failure")
        
        return {
            "status": "processing",
            "session_id": session_id,
            "message": "Processing pipeline failure"
        }
    
    async def _process_fix_branch_pipeline(
        self,
        data: Dict[str, Any],
        subscription_id: Optional[str] = None,
        branch_name: str = ""
    ) -> Dict[str, Any]:
        """Process pipeline events for fix branches"""
        pipeline_status = data.get("object_attributes", {}).get("status")
        
        # Extract session ID from branch name
        session_id = safe_extract_session_id(branch_name)
        if not session_id:
            log.warning(f"Could not extract session ID from fix branch: {branch_name}")
            return {"status": "error", "reason": "Invalid fix branch format"}
        
        try:
            branch_info = extract_branch_info(branch_name)
            branch_type = branch_info["branch_type"]
        except Exception as e:
            log.warning(f"Could not parse branch info from {branch_name}: {str(e)}")
            return {"status": "error", "reason": "Invalid fix branch format"}
        
        # Check if session exists
        session = await self.db.get_session(session_id)
        if not session:
            log.warning(f"No session found for fix branch: {branch_name} (session: {session_id})")
            return {"status": "error", "reason": "Session not found"}
        
        # Update session with fix branch info
        update_data = {
            "fix_branch": branch_name,
            "fix_pipeline_id": str(data.get("object_attributes", {}).get("id")),
            "fix_pipeline_status": pipeline_status,
            "fix_branch_type": branch_type,
            "updated_at": datetime.utcnow()
        }
        
        await self.db.update_session(session_id, update_data)
        
        # Publish event based on pipeline status
        if pipeline_status == "success":
            event_type = f"{branch_type}_fix_success"
            message = f"Fix branch pipeline succeeded for {branch_type}"
            
            # Handle fix iteration success
            if self.fix_iteration_handler:
                try:
                    await self.fix_iteration_handler.handle_fix_branch_success(
                        session_id, branch_name, 
                        str(data.get("object_attributes", {}).get("id")), 
                        data
                    )
                except Exception as e:
                    log.error(f"Error handling fix branch success: {e}")
                    
        elif pipeline_status == "failed":
            event_type = f"{branch_type}_fix_failed"
            message = f"Fix branch pipeline failed for {branch_type}"
            
            # Handle fix iteration failure and trigger new iteration
            if self.fix_iteration_handler:
                try:
                    iteration_result = await self.fix_iteration_handler.handle_fix_branch_failure(
                        session_id, branch_name, 
                        str(data.get("object_attributes", {}).get("id")), 
                        data
                    )
                    
                    # If iteration was triggered, update the message
                    if iteration_result.get("status") == "iteration_triggered":
                        message = f"Fix iteration #{iteration_result.get('attempt_number')} triggered"
                    elif iteration_result.get("status") == "max_attempts_reached":
                        message = f"Maximum fix attempts reached for {branch_type}"
                        
                except Exception as e:
                    log.error(f"Error handling fix branch failure: {e}")
        else:
            return {"status": "ignored", "reason": f"Fix pipeline status: {pipeline_status}"}
        
        await self.queue_publisher.publish_event(
            event_type=event_type,
            session_id=session_id,
            data={**session, **update_data}
        )
        
        log.info(f"Processed fix branch pipeline: {branch_name} -> {event_type}")
        
        return {
            "status": "processing",
            "session_id": session_id,
            "message": message
        }
    
    async def _process_push_event(
        self,
        data: Dict[str, Any],
        subscription_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process push events (branch creation/updates)"""
        branch_name = data.get("ref", "").replace("refs/heads/", "")
        
        # Only interested in fix branches
        if not is_fix_branch(branch_name):
            return {"status": "ignored", "reason": "Not a fix branch"}
        
        # Extract session ID from branch name
        session_id = safe_extract_session_id(branch_name)
        if not session_id:
            log.warning(f"Could not extract session ID from fix branch: {branch_name}")
            return {"status": "error", "reason": "Invalid fix branch format"}
        
        # Check if session exists
        session = await self.db.get_session(session_id)
        if not session:
            log.warning(f"No session found for fix branch: {branch_name} (session: {session_id})")
            return {"status": "error", "reason": "Session not found"}
        
        try:
            branch_info = extract_branch_info(branch_name)
        except Exception as e:
            log.warning(f"Could not parse branch info from {branch_name}: {str(e)}")
            return {"status": "error", "reason": "Invalid fix branch format"}
        
        # Update session with fix branch creation info
        update_data = {
            "fix_branch": branch_name,
            "fix_branch_type": branch_info["branch_type"],
            "fix_branch_created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        await self.db.update_session(session_id, update_data)
        
        # Publish fix branch created event
        await self.queue_publisher.publish_event(
            event_type="fix_branch_created",
            session_id=session_id,
            data={**session, **update_data}
        )
        
        log.info(f"Fix branch created: {branch_name} for session {session_id}")
        
        return {
            "status": "processing",
            "session_id": session_id,
            "message": f"Fix branch created: {branch_name}"
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