"""Queue Processor - Contains all webhook analysis logic moved from api/webhooks.py"""
import json
import asyncio
import aio_pika
import redis.asyncio as redis
from typing import Dict, Any, Optional, List
from datetime import datetime
from utils.logger import log
from config import settings
from agents.pipeline_agent import PipelineAgent
from agents.quality_agent import QualityAgent
from db.session_manager import SessionManager
from services.vector_store import VectorStore

class QueueProcessor:
    """Process events from queue - contains all analysis logic from webhooks.py"""
    
    def __init__(self):
        self.queue_type = settings.queue_type
        self.session_manager = SessionManager()
        self.vector_store = VectorStore()
        self.pipeline_agent = PipelineAgent()
        self.quality_agent = QualityAgent()
        self.processing = False
        self.connection = None
        self.channel = None
        self.redis_client = None
        
    async def start(self):
        """Start processing queue messages"""
        self.processing = True
        log.info(f"Starting {self.queue_type} queue processor")
        
        # Initialize components
        await self.session_manager.init_pool()
        await self.vector_store.init()
        
        if self.queue_type == 'rabbitmq':
            await self.start_rabbitmq()
        else:
            await self.start_redis()
    
    async def start_rabbitmq(self):
        """Start RabbitMQ consumer"""
        try:
            self.connection = await aio_pika.connect_robust(settings.rabbitmq_url)
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=10)
            
            queue = await self.channel.declare_queue(settings.queue_name, durable=True)
            
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        await self.process_message(json.loads(message.body))
                        
        except Exception as e:
            log.error(f"RabbitMQ error: {e}")
            await asyncio.sleep(5)
            if self.processing:
                await self.start_rabbitmq()
    
    async def start_redis(self):
        """Start Redis consumer"""
        try:
            self.redis_client = await redis.from_url(settings.redis_url, decode_responses=True)
            
            while self.processing:
                message = await self.redis_client.blpop(settings.queue_name, timeout=30)
                if message:
                    _, data = message
                    await self.process_message(json.loads(data))
                    
        except Exception as e:
            log.error(f"Redis error: {e}")
            await asyncio.sleep(5)
            if self.processing:
                await self.start_redis()
    
    async def process_message(self, message: Dict[str, Any]):
        """Process a queue message"""
        try:
            event_type = message.get('event_type')
            session_id = message.get('session_id')
            
            log.info(f"Processing {event_type} event for session {session_id}")
            
            if event_type == 'gitlab_pipeline':
                await self.process_gitlab_pipeline(message)
            elif event_type == 'sonarqube_quality':
                await self.process_sonarqube_quality(message)
                
        except Exception as e:
            log.error(f"Failed to process message: {e}", exc_info=True)
    
    # ===== MOVED FROM api/webhooks.py =====
    
    async def process_gitlab_pipeline(self, event_data: Dict[str, Any]):
        """Process GitLab pipeline event (moved from webhooks.py)"""
        session_id = event_data['session_id']
        webhook_data = event_data['webhook_data']
        pipeline_status = event_data['pipeline_status']
        project_id = event_data['project_id']
        ref = webhook_data.get("object_attributes", {}).get("ref")
        
        # Handle successful pipelines
        if pipeline_status == "success":
            await self.handle_pipeline_success(project_id, ref)
            return
        
        # Only process failures
        if pipeline_status != "failed":
            return
        
        # Check for existing sessions and handle fix branch failures
        existing_sessions = await self.session_manager.get_active_sessions()
        
        # Check if this is a quality gate failure
        is_quality_failure = await self.check_quality_gate_in_logs(webhook_data)
        
        # Determine session type
        if is_quality_failure:
            session_type = "quality"
            fix_branch_prefix = "fix/sonarqube_"
        else:
            session_type = "pipeline"
            fix_branch_prefix = "fix/pipeline_"
        
        # Handle fix branch failures (AUTO-RETRY LOGIC)
        if ref and ref.startswith(fix_branch_prefix):
            for session in existing_sessions:
                if (session.get("session_type") == session_type and 
                    session.get("project_id") == project_id and
                    session.get("status") == "active"):
                    
                    fix_attempts = await self.session_manager.get_fix_attempts(session['id'])
                    for attempt in fix_attempts:
                        if attempt.get("branch_name") == ref:
                            if attempt["status"] == "pending":
                                await self.session_manager.update_fix_attempt(
                                    session['id'],
                                    attempt["attempt_number"],
                                    "failed",
                                    error_details=f"{session_type.capitalize()} still failing"
                                )
                            
                            # Check iteration limit
                            actual_attempt_count = len(fix_attempts)
                            max_retry_attempts = settings.max_fix_attempts
                            
                            if actual_attempt_count >= max_retry_attempts:
                                log.warning(f"Maximum retry attempts reached for session {session['id']}")
                                await self.session_manager.add_message(
                                    session['id'],
                                    "assistant",
                                    f"⚠️ Maximum fix attempts ({max_retry_attempts}) reached."
                                )
                                return
                            
                            # AUTO-RETRY
                            if actual_attempt_count < max_retry_attempts:
                                log.info(f"Auto-triggering retry for session {session['id']}")
                                
                                context = await self.session_manager.get_session_context(session['id'])
                                retry_message = f"The pipeline is still failing. This is attempt {actual_attempt_count + 1} of {max_retry_attempts}."
                                
                                await self.session_manager.add_message(session['id'], "user", retry_message)
                                
                                full_session = await self.session_manager.get_session(session['id'])
                                conversation_history = full_session.get("conversation_history", [])
                                
                                if session_type == "quality":
                                    response = await self.quality_agent.handle_user_message(
                                        session['id'], retry_message, conversation_history, context
                                    )
                                else:
                                    response = await self.pipeline_agent.handle_user_message(
                                        session['id'], retry_message, conversation_history, context
                                    )
                                
                                await self.session_manager.add_message(session['id'], "assistant", str(response))
                            return
        
        # Check for existing active session
        for session in existing_sessions:
            if (session.get("session_type") == session_type and 
                session.get("project_id") == project_id and
                session.get("status") == "active" and
                not ref.startswith(fix_branch_prefix if ref else "")):
                log.info(f"Found existing {session_type} session {session['id']}")
                return
        
        # Create new session based on type
        if is_quality_failure:
            await self.create_quality_session(session_id, webhook_data)
        else:
            await self.create_pipeline_session(session_id, webhook_data)
    
    async def process_sonarqube_quality(self, event_data: Dict[str, Any]):
        """Process SonarQube event (moved from webhooks.py)"""
        session_id = event_data['session_id']
        webhook_data = event_data['webhook_data']
        sonarqube_key = event_data['sonarqube_key']
        
        # Map to GitLab project
        gitlab_project_id = await self.get_gitlab_project_id(sonarqube_key)
        
        if not gitlab_project_id:
            log.error(f"Could not map SonarQube project {sonarqube_key}")
            return
        
        # Update session with GitLab project
        await self.session_manager.update_session_metadata(
            session_id,
            {"project_id": gitlab_project_id}
        )
        
        # Start analysis
        await self.analyze_quality_issues(
            session_id,
            sonarqube_key,
            gitlab_project_id,
            webhook_data
        )
    
    async def check_quality_gate_in_logs(self, webhook_data: Dict[str, Any]) -> bool:
        """Check if pipeline failure is due to quality gate (moved from webhooks.py)"""
        from tools.gitlab import get_job_logs
        
        failed_jobs = [job for job in webhook_data.get("builds", []) if job.get("status") == "failed"]
        
        if not failed_jobs:
            return False
        
        failed_jobs.sort(key=lambda x: x.get("finished_at", ""), reverse=True)
        most_recent_failed_job = failed_jobs[0]
        project_id = str(webhook_data.get("project", {}).get("id"))
        
        try:
            job_id = str(most_recent_failed_job.get("id"))
            job_name = most_recent_failed_job.get("name", "")
            
            if any(keyword in job_name.lower() for keyword in ['sonar', 'quality']):
                return True
            
            logs = await get_job_logs(job_id, project_id)
            
            quality_indicators = [
                "Quality Gate failure",
                "QUALITY GATE STATUS: FAILED",
                "Quality gate failed",
                "SonarQube analysis reported",
                "Quality gate status: ERROR"
            ]
            
            logs_lower = logs.lower()
            if any(indicator.lower() in logs_lower for indicator in quality_indicators):
                return True
                
        except Exception as e:
            log.warning(f"Could not fetch logs: {e}")
        
        return False
    
    async def handle_pipeline_success(self, project_id: str, ref: str):
        """Handle successful pipeline (moved from webhooks.py)"""
        log.info(f"Handling pipeline success: project={project_id}, ref={ref}")
        sessions = await self.session_manager.get_active_sessions()
        
        if ref and ref.startswith("fix/"):
            for session in sessions:
                if session.get("project_id") == project_id and session.get("status") == "active":
                    fix_attempts = await self.session_manager.get_fix_attempts(session["id"])
                    
                    for attempt in fix_attempts:
                        if attempt.get('branch_name') == ref and attempt["status"] == "pending":
                            # Mark as successful
                            await self.session_manager.update_fix_attempt(
                                session["id"],
                                attempt["attempt_number"],
                                "success"
                            )
                            
                            # Store in vector DB
                            tracked_files = await self.session_manager.get_tracked_files(session['id'])
                            if tracked_files:
                                fix_files = {}
                                for file_path, file_data in tracked_files.items():
                                    if file_data.get('status') == 'success':
                                        fix_files[file_path] = file_data.get('content', '')
                                
                                if fix_files:
                                    await self.vector_store.store_successful_fix(
                                        session, attempt, fix_files
                                    )
                            
                            await self.session_manager.add_message(
                                session["id"],
                                "assistant",
                                f"✅ Fix successful! Pipeline passed on branch `{ref}`."
                            )
                            return
    
    async def create_quality_session(self, session_id: str, webhook_data: Dict[str, Any]):
        """Create quality session (moved from webhooks.py)"""
        project = webhook_data.get("project", {})
        pipeline = webhook_data.get("object_attributes", {})
        
        sonarqube_key = project.get("name")
        gitlab_project_id = str(project.get("id"))
        
        current_fix_branch, parent_session_id = await self.get_existing_fix_branch("quality", gitlab_project_id)
        
        metadata = {
            "sonarqube_key": sonarqube_key,
            "webhook_data": webhook_data,
            "current_fix_branch": current_fix_branch,
            "parent_session_id": parent_session_id
        }
        
        await self.session_manager.update_session_metadata(session_id, metadata)
        
        await self.session_manager.add_message(
            session_id,
            "system",
            f"Quality gate failure detected for {project.get('name')}"
        )
        
        await self.analyze_quality_from_pipeline(
            session_id,
            sonarqube_key,
            gitlab_project_id,
            webhook_data
        )
    
    async def create_pipeline_session(self, session_id: str, webhook_data: Dict[str, Any]):
        """Create pipeline session (moved from webhooks.py)"""
        project = webhook_data.get("project", {})
        project_id = str(project.get("id"))
        
        current_fix_branch, parent_session_id = await self.get_existing_fix_branch("pipeline", project_id)
        
        metadata = {
            "webhook_data": webhook_data,
            "current_fix_branch": current_fix_branch,
            "parent_session_id": parent_session_id
        }
        
        await self.session_manager.update_session_metadata(session_id, metadata)
        
        await self.session_manager.add_message(
            session_id,
            "system",
            f"Pipeline failure detected for {project.get('name')}"
        )
        
        await self.analyze_pipeline_failure(
            session_id,
            project_id,
            str(webhook_data.get("object_attributes", {}).get("id")),
            webhook_data
        )
    
    async def analyze_pipeline_failure(self, session_id: str, project_id: str, pipeline_id: str, webhook_data: Dict):
        """Analyze pipeline failure (moved from webhooks.py)"""
        try:
            log.info(f"Starting pipeline analysis for session {session_id}")
            
            analysis = await self.pipeline_agent.analyze_failure(
                session_id, project_id, pipeline_id, webhook_data
            )
            
            if isinstance(analysis, dict) and "content" in analysis:
                content = analysis["content"]
                if isinstance(content, list) and len(content) > 0:
                    analysis = content[0].get("text", str(analysis))
            
            await self.session_manager.add_message(session_id, "assistant", analysis)
            log.info(f"Pipeline analysis complete for session {session_id}")
            
        except Exception as e:
            log.error(f"Pipeline analysis failed: {e}", exc_info=True)
            await self.session_manager.add_message(
                session_id, "assistant", f"Analysis failed: {str(e)}"
            )
    
    async def analyze_quality_from_pipeline(self, session_id: str, project_key: str, gitlab_project_id: str, webhook_data: Dict):
        """Analyze quality from pipeline (moved from webhooks.py)"""
        try:
            log.info(f"Starting quality analysis from pipeline for session {session_id}")
            
            from tools.sonarqube import get_project_issues, get_project_metrics, get_project_quality_gate_status
            
            quality_status = await get_project_quality_gate_status(project_key)
            project_status = quality_status.get("projectStatus", {})
            
            if project_status.get("status") == "NONE" or not project_status:
                log.warning(f"No quality gate configured for {project_key}")
                await self.session_manager.update_session_metadata(
                    session_id, {"session_type": "pipeline"}
                )
                return
            
            bugs = await get_project_issues(project_key, types="BUG", limit=500)
            vulnerabilities = await get_project_issues(project_key, types="VULNERABILITY", limit=500)
            code_smells = await get_project_issues(project_key, types="CODE_SMELL", limit=500)
            
            await self.session_manager.update_quality_metrics(
                session_id,
                {
                    "total_issues": len(bugs) + len(vulnerabilities) + len(code_smells),
                    "bug_count": len(bugs),
                    "vulnerability_count": len(vulnerabilities),
                    "code_smell_count": len(code_smells)
                }
            )
            
            enhanced_webhook_data = {**webhook_data, "qualityGate": project_status}
            
            analysis = await self.quality_agent.analyze_quality_issues(
                session_id, project_key, gitlab_project_id, enhanced_webhook_data
            )
            
            if isinstance(analysis, dict) and "content" in analysis:
                content = analysis["content"]
                if isinstance(content, list) and len(content) > 0:
                    analysis = content[0].get("text", str(analysis))
            
            await self.session_manager.add_message(session_id, "assistant", analysis)
            log.info(f"Quality analysis complete for session {session_id}")
            
        except Exception as e:
            log.error(f"Quality analysis failed: {e}", exc_info=True)
            await self.session_manager.add_message(
                session_id, "assistant", f"Quality analysis failed: {str(e)}"
            )
    
    async def analyze_quality_issues(self, session_id: str, project_key: str, gitlab_project_id: str, webhook_data: Dict):
        """Analyze quality issues (moved from webhooks.py)"""
        try:
            log.info(f"Starting quality analysis for session {session_id}")
            
            from tools.sonarqube import get_project_issues, get_project_metrics
            
            bugs = await get_project_issues(project_key, types="BUG", limit=500)
            vulnerabilities = await get_project_issues(project_key, types="VULNERABILITY", limit=500)
            code_smells = await get_project_issues(project_key, types="CODE_SMELL", limit=500)
            
            await self.session_manager.update_quality_metrics(
                session_id,
                {
                    "total_issues": len(bugs) + len(vulnerabilities) + len(code_smells),
                    "bug_count": len(bugs),
                    "vulnerability_count": len(vulnerabilities),
                    "code_smell_count": len(code_smells)
                }
            )
            
            analysis = await self.quality_agent.analyze_quality_issues(
                session_id, project_key, gitlab_project_id, webhook_data
            )
            
            if isinstance(analysis, dict) and "content" in analysis:
                content = analysis["content"]
                if isinstance(content, list) and len(content) > 0:
                    analysis = content[0].get("text", str(analysis))
            
            await self.session_manager.add_message(session_id, "assistant", analysis)
            log.info(f"Quality analysis complete for session {session_id}")
            
        except Exception as e:
            log.error(f"Quality analysis failed: {e}", exc_info=True)
            await self.session_manager.add_message(
                session_id, "assistant", f"Analysis failed: {str(e)}"
            )
    
    async def get_existing_fix_branch(self, session_type: str, project_id: str) -> tuple[Optional[str], Optional[str]]:
        """Get existing fix branch (moved from webhooks.py)"""
        existing_sessions = await self.session_manager.get_active_sessions()
        
        for session in existing_sessions:
            if (session.get("session_type") == session_type and 
                session.get("project_id") == project_id and
                session.get("current_fix_branch") and
                session.get("merge_request_url")):
                return session.get("current_fix_branch"), session["id"]
        
        return None, None
    
    async def get_gitlab_project_id(self, sonarqube_key: str) -> Optional[str]:
        """Map SonarQube to GitLab (moved from webhooks.py)"""
        from tools.gitlab import get_gitlab_client
        
        log.info(f"Looking up GitLab project for SonarQube key: {sonarqube_key}")
        
        async with await get_gitlab_client() as client:
            try:
                if "/" in sonarqube_key:
                    encoded_path = sonarqube_key.replace("/", "%2F")
                    response = await client.get(f"/projects/{encoded_path}")
                    if response.status_code == 200:
                        return str(response.json().get("id"))
                
                search_params = {"search": sonarqube_key, "simple": "true"}
                response = await client.get("/projects", params=search_params)
                
                if response.status_code == 200:
                    projects = response.json()
                    for project in projects:
                        if project.get("name") == sonarqube_key:
                            return str(project.get("id"))
                
                return None
                
            except Exception as e:
                log.error(f"Error looking up GitLab project: {e}")
                return None
    
    async def stop(self):
        """Stop processing"""
        self.processing = False
        if self.connection:
            await self.connection.close()
        if self.redis_client:
            await self.redis_client.close()