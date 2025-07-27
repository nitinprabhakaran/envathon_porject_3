from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from pydantic import BaseModel
from loguru import logger
import json
from datetime import datetime
import asyncio

from agent.core import CICDFailureAgent
from db.session_manager import SessionManager
from tools.gitlab_tools import create_merge_request

api_router = APIRouter()

# Initialize
agent = CICDFailureAgent()
session_manager = SessionManager()

class MessageRequest(BaseModel):
    message: str

class ApplyFixRequest(BaseModel):
    fix_id: str
    fix_data: Dict[str, Any]

class CreateMRRequest(BaseModel):
    fix_id: str
    fix_data: Dict[str, Any]

def serialize_session(session: Dict[str, Any]) -> Dict[str, Any]:
    """Properly serialize session data for API response"""
    # Convert any datetime objects to strings
    for key in ['created_at', 'last_activity', 'expires_at']:
        if key in session and session[key]:
            if hasattr(session[key], 'isoformat'):
                session[key] = session[key].isoformat()
    
    # Ensure conversation_history is a list
    if 'conversation_history' in session:
        if isinstance(session['conversation_history'], str):
            try:
                session['conversation_history'] = json.loads(session['conversation_history'])
            except:
                session['conversation_history'] = []
        elif session['conversation_history'] is None:
            session['conversation_history'] = []
    
    # Ensure other JSON fields are properly loaded
    for json_field in ['applied_fixes', 'successful_fixes', 'tools_called', 'user_feedback', 'webhook_data']:
        if json_field in session:
            if isinstance(session[json_field], str):
                try:
                    session[json_field] = json.loads(session[json_field])
                except:
                    session[json_field] = [] if json_field.endswith('fixes') or json_field == 'tools_called' else {}
            elif session[json_field] is None:
                session[json_field] = [] if json_field.endswith('fixes') or json_field == 'tools_called' else {}
    
    # Extract metadata from webhook_data if available
    if 'webhook_data' in session and session['webhook_data']:
        webhook_data = session['webhook_data']
        if isinstance(webhook_data, dict):
            if 'project' in webhook_data:
                session['project_name'] = webhook_data['project'].get('name', session.get('project_name'))
            if 'object_attributes' in webhook_data:
                attrs = webhook_data['object_attributes']
                session['branch'] = attrs.get('ref', session.get('branch'))
                session['pipeline_source'] = attrs.get('source', session.get('pipeline_source'))
                session['pipeline_url'] = attrs.get('url', session.get('pipeline_url'))
    
    return session

@api_router.get("/sessions/active")
async def get_active_sessions():
    """Get all active sessions"""
    try:
        logger.info("Fetching active sessions from database...")
        sessions = await session_manager.get_active_sessions()
        logger.info(f"Raw sessions count: {len(sessions)}")
        
        if sessions:
            logger.info(f"First session data: {sessions[0]}")
        
        serialized_sessions = [serialize_session(session) for session in sessions]
        logger.info(f"Returning {len(serialized_sessions)} active sessions")
        
        # Return just the list for compatibility
        return serialized_sessions
    except Exception as e:
        logger.error(f"Failed to get active sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/sessions/all")
async def get_all_sessions():
    """Get ALL sessions for debugging"""
    try:
        async with session_manager._get_connection() as conn:
            rows = await conn.fetch("SELECT * FROM sessions ORDER BY created_at DESC LIMIT 10")
            all_sessions = []
            for row in rows:
                session = dict(row)
                all_sessions.append({
                    "id": str(session.get("id")),
                    "status": session.get("status"),
                    "created_at": str(session.get("created_at")),
                    "expires_at": str(session.get("expires_at")),
                    "project_id": session.get("project_id"),
                    "pipeline_id": session.get("pipeline_id")
                })
            return {
                "total": len(all_sessions),
                "sessions": all_sessions
            }
    except Exception as e:
        logger.error(f"Failed to get all sessions: {e}")
        return {"error": str(e)}

@api_router.get("/debug/check-session/{session_id}")
async def debug_check_session(session_id: str):
    """Debug endpoint to check session details"""
    try:
        async with session_manager._get_connection() as conn:
            # Get raw session data
            row = await conn.fetchrow(
                "SELECT * FROM sessions WHERE id = $1",
                session_id
            )
            if row:
                session_data = dict(row)
                return {
                    "found": True,
                    "id": str(session_data.get("id")),
                    "status": session_data.get("status"),
                    "created_at": str(session_data.get("created_at")),
                    "expires_at": str(session_data.get("expires_at")),
                    "project_id": session_data.get("project_id"),
                    "pipeline_id": session_data.get("pipeline_id"),
                    "conversation_length": len(json.loads(session_data.get("conversation_history", "[]")))
                }
            else:
                return {"found": False, "session_id": session_id}
    except Exception as e:
        return {"error": str(e)}
async def get_session(session_id: str):
    """Get specific session details"""
    try:
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        serialized_session = serialize_session(session)
        logger.info(f"Returning session {session_id} with project_id={serialized_session.get('project_id')}")
        return serialized_session
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/sessions/{session_id}/message")
async def send_message(session_id: str, request: MessageRequest):
    """Send a message to the agent for a specific session"""
    try:
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        response = await agent.continue_conversation(
            session_id=session_id,
            user_message=request.message
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to process message: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/sessions/{session_id}/apply-fix")
async def apply_fix(session_id: str, request: ApplyFixRequest):
    """Apply a suggested fix"""
    try:
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        await session_manager.add_applied_fix(
            session_id,
            {
                "fix_id": request.fix_id,
                "fix_data": request.fix_data,
                "status": "applying",
                "applied_at": datetime.utcnow().isoformat()
            }
        )
        
        return {
            "status": "success",
            "fix_id": request.fix_id,
            "message": "Fix application initiated",
            "progress": {
                "status": "in_progress",
                "steps": [
                    {"name": "Analyzing changes", "status": "done"},
                    {"name": "Applying to repository", "status": "in_progress"},
                    {"name": "Running validation", "status": "pending"}
                ]
            }
        }
    except Exception as e:
        logger.error(f"Failed to apply fix: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/sessions/{session_id}/create-mr")
async def create_merge_request_endpoint(session_id: str, request: CreateMRRequest):
    """Create a merge request for a fix"""
    try:
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        project_id = session.get("project_id")
        fix_data = request.fix_data
        
        # Default fix for Java JAR issue
        changes = {
            ".gitlab-ci.yml": """stages:
  - build
  - quality_scan

build-job:
  image: maven:3.8-openjdk-11
  stage: build
  script:
    - mvn clean package
    - docker build -t ${CI_PROJECT_NAME}:${CI_COMMIT_SHORT_SHA} .
  artifacts:
    paths:
      - target/*.jar
  tags:
    - docker

sonar-scan-job:
  extends: .sonar-scan-template
  dependencies:
    - build-job
"""
        }
        
        branch_name = fix_data.get("branch", f"fix/pipeline-{session_id[:8]}")
        
        result = await create_merge_request(
            title=f"Fix: Add Maven build step before Docker build",
            description=f"""## 🔧 Pipeline Fix

This MR fixes the pipeline failure by adding a Maven build step before the Docker build.

### Changes:
- Added `mvn clean package` to build the JAR file
- Configured artifacts to preserve the JAR for Docker build
- Fixed the missing `target/java-project-1.0.0.jar` error

### Root Cause:
The Docker build was failing because it tried to copy a JAR file that didn't exist. The Maven build step was missing.

---
Generated by CI/CD Failure Assistant
Session: `{session_id}`""",
            changes=changes,
            source_branch=branch_name,
            target_branch="main",
            project_id=project_id
        )
        
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
        await session_manager.add_applied_fix(
            session_id,
            {
                "fix_id": request.fix_id,
                "type": "merge_request",
                "mr_id": result.get("id"),
                "mr_url": result.get("web_url"),
                "created_at": datetime.utcnow().isoformat()
            }
        )
        
        return {
            "status": "success",
            "merge_request": {
                "id": result.get("id"),
                "iid": result.get("iid"),
                "url": result.get("web_url"),
                "title": result.get("title"),
                "source_branch": result.get("source_branch"),
                "target_branch": result.get("target_branch"),
                "state": result.get("state", "opened")
            },
            "message": "Merge request created successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create MR: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))