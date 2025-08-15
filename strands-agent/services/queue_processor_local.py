"""Queue Processor for Local Development (RabbitMQ/Redis)"""
import json
import asyncio
import aio_pika
import redis.asyncio as redis
from typing import Dict, Any, Optional
from utils.logger import log
from config import settings
from agents.pipeline_agent import PipelineAgent
from agents.quality_agent import QualityAgent
from db.session_manager import SessionManager
from services.vector_store import VectorStore

class LocalQueueProcessor:
    """Process events from RabbitMQ or Redis queue"""
    
    def __init__(self):
        self.queue_type = settings.queue_type  # 'rabbitmq' or 'redis'
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
        
        # Initialize vector store
        await self.vector_store.init()
        
        if self.queue_type == 'rabbitmq':
            await self.start_rabbitmq()
        else:
            await self.start_redis()
    
    async def start_rabbitmq(self):
        """Start RabbitMQ consumer"""
        try:
            # Connect to RabbitMQ
            self.connection = await aio_pika.connect_robust(
                settings.rabbitmq_url,
                loop=asyncio.get_event_loop()
            )
            
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=10)
            
            # Declare queue
            queue = await self.channel.declare_queue(
                settings.queue_name,
                durable=True
            )
            
            # Start consuming
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        await self.process_message(json.loads(message.body))
                        
        except Exception as e:
            log.error(f"RabbitMQ error: {e}")
            await asyncio.sleep(5)
            if self.processing:
                await self.start_rabbitmq()  # Reconnect
    
    async def start_redis(self):
        """Start Redis queue consumer"""
        try:
            self.redis_client = await redis.from_url(
                settings.redis_url,
                decode_responses=True
            )
            
            while self.processing:
                # Blocking pop from list
                message = await self.redis_client.blpop(
                    settings.queue_name,
                    timeout=30
                )
                
                if message:
                    _, data = message
                    await self.process_message(json.loads(data))
                    
        except Exception as e:
            log.error(f"Redis error: {e}")
            await asyncio.sleep(5)
            if self.processing:
                await self.start_redis()  # Reconnect
    
    async def process_message(self, message: Dict[str, Any]):
        """Process a queue message"""
        try:
            event_type = message.get('event_type')
            session_id = message.get('session_id')
            
            log.info(f"Processing {event_type} event for session {session_id}")
            
            if event_type == 'gitlab_pipeline':
                await self.process_gitlab_event(message)
            elif event_type == 'sonarqube_quality':
                await self.process_sonarqube_event(message)
            else:
                log.warning(f"Unknown event type: {event_type}")
                
        except Exception as e:
            log.error(f"Failed to process message: {e}", exc_info=True)
    
    async def process_gitlab_event(self, event_data: Dict[str, Any]):
        """Process GitLab pipeline event"""
        session_id = event_data['session_id']
        webhook_data = event_data['webhook_data']
        pipeline_status = event_data['pipeline_status']
        
        # Handle successful pipelines
        if pipeline_status == "success":
            await self.handle_pipeline_success(session_id, webhook_data)
            return
        
        # Handle failures
        if pipeline_status == "failed":
            # Check if it's a quality gate failure
            is_quality = await self.check_quality_gate_failure(webhook_data)
            
            # Update session type if quality
            if is_quality:
                await self.session_manager.update_session_metadata(
                    session_id,
                    {"session_type": "quality"}
                )
            
            # Get full session context
            context = await self.session_manager.get_session_context(session_id)
            
            if not context:
                log.error(f"Session {session_id} not found")
                return
            
            # Analyze failure
            try:
                if is_quality:
                    # Extract SonarQube project key
                    project = webhook_data.get("project", {})
                    sonarqube_key = project.get("name")
                    
                    analysis = await self.quality_agent.analyze_quality_issues(
                        session_id,
                        sonarqube_key,
                        context.project_id,
                        webhook_data
                    )
                else:
                    analysis = await self.pipeline_agent.analyze_failure(
                        session_id,
                        context.project_id,
                        context.pipeline_id,
                        webhook_data
                    )
                
                # Store analysis
                await self.session_manager.add_message(session_id, "assistant", analysis)
                
                log.info(f"Completed analysis for session {session_id}")
                
            except Exception as e:
                log.error(f"Analysis failed: {e}", exc_info=True)
                await self.session_manager.add_message(
                    session_id,
                    "assistant",
                    f"Analysis failed: {str(e)}"
                )
    
    async def process_sonarqube_event(self, event_data: Dict[str, Any]):
        """Process SonarQube quality event"""
        session_id = event_data['session_id']
        webhook_data = event_data['webhook_data']
        sonarqube_key = event_data['sonarqube_key']
        
        # Map to GitLab project (simplified for local)
        gitlab_project_id = event_data.get('gitlab_project_id')
        if not gitlab_project_id:
            # Try to extract from naming pattern
            gitlab_project_id = sonarqube_key.replace("_", "/")
        
        # Update session with GitLab project
        await self.session_manager.update_session_metadata(
            session_id,
            {"project_id": gitlab_project_id}
        )
        
        # Get context
        context = await self.session_manager.get_session_context(session_id)
        
        if not context:
            log.error(f"Session {session_id} not found")
            return
        
        try:
            # Analyze quality issues
            analysis = await self.quality_agent.analyze_quality_issues(
                session_id,
                sonarqube_key,
                gitlab_project_id,
                webhook_data
            )
            
            # Store analysis
            await self.session_manager.add_message(session_id, "assistant", analysis)
            
            log.info(f"Completed quality analysis for session {session_id}")
            
        except Exception as e:
            log.error(f"Quality analysis failed: {e}", exc_info=True)
            await self.session_manager.add_message(
                session_id,
                "assistant",
                f"Quality analysis failed: {str(e)}"
            )
    
    async def handle_pipeline_success(self, session_id: str, webhook_data: Dict[str, Any]):
        """Handle successful pipeline - store fix if applicable"""
        project_id = str(webhook_data.get("project", {}).get("id"))
        ref = webhook_data.get("object_attributes", {}).get("ref")
        
        # Check if this is a fix branch
        if not ref or not ref.startswith("fix/"):
            return
        
        # Find the session that created this fix
        sessions = await self.session_manager.get_active_sessions()
        
        for session in sessions:
            if session.get("project_id") != project_id:
                continue
                
            # Check fix attempts
            fix_attempts = await self.session_manager.get_fix_attempts(session['id'])
            
            for attempt in fix_attempts:
                if attempt.get("branch_name") == ref and attempt.get("status") == "pending":
                    # Mark as successful
                    await self.session_manager.update_fix_attempt(
                        session['id'],
                        attempt["attempt_number"],
                        "success"
                    )
                    
                    # Get tracked files for this fix
                    tracked_files = await self.session_manager.get_tracked_files(session['id'])
                    
                    # Store in vector DB
                    if tracked_files:
                        # Convert tracked files to simple dict
                        fix_files = {}
                        for file_path, file_data in tracked_files.items():
                            if file_data.get('status') == 'success':
                                fix_files[file_path] = file_data.get('content', '')
                        
                        if fix_files:
                            success = await self.vector_store.store_successful_fix(
                                session,
                                attempt,
                                fix_files
                            )
                            
                            if success:
                                log.info(f"Stored successful fix for session {session['id']}")
                    
                    # Add success message
                    await self.session_manager.add_message(
                        session['id'],
                        "assistant",
                        f"✅ Fix successful! Pipeline passed on branch `{ref}`."
                    )
                    
                    return
    
    async def check_quality_gate_failure(self, webhook_data: Dict[str, Any]) -> bool:
        """Check if pipeline failure is due to quality gate"""
        failed_jobs = [
            job for job in webhook_data.get("builds", [])
            if job.get("status") == "failed"
        ]
        
        for job in failed_jobs:
            job_name = job.get("name", "").lower()
            if any(keyword in job_name for keyword in ["sonar", "quality"]):
                return True
        
        return False
    
    async def stop(self):
        """Stop processing"""
        self.processing = False
        
        if self.connection:
            await self.connection.close()
        
        if self.redis_client:
            await self.redis_client.close()
        
        log.info("Queue processor stopped")