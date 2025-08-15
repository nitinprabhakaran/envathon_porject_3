"""Queue processor for handling webhook events from webhook-handler"""
import json
import asyncio
from typing import Dict, Any, Optional
import aio_pika
import boto3
from datetime import datetime
from utils.logger import log
from config import settings
from db.session_manager import SessionManager
from agents.pipeline_agent import PipelineAgent
from agents.quality_agent import QualityAgent
from services.vector_store import VectorStore

class QueueProcessor:
    """Process webhook events from message queue"""
    
    def __init__(self):
        self.session_manager = SessionManager()
        self.pipeline_agent = PipelineAgent()
        self.quality_agent = QualityAgent()
        self.vector_store = VectorStore()
        self.connection = None
        self.channel = None
        self.sqs_client = None
        self.running = False
        
        if settings.queue_type == "sqs":
            self.sqs_client = boto3.client('sqs', region_name=settings.aws_region)
    
    async def start(self):
        """Start processing queue messages"""
        self.running = True
        log.info("Starting queue processor...")
        
        if settings.queue_type == "rabbitmq":
            await self._start_rabbitmq()
        elif settings.queue_type == "sqs":
            await self._start_sqs()
    
    async def _start_rabbitmq(self):
        """Start RabbitMQ consumer"""
        try:
            self.connection = await aio_pika.connect_robust(settings.rabbitmq_url)
            self.channel = await self.connection.channel()
            
            # Set prefetch count
            await self.channel.set_qos(prefetch_count=1)
            
            # Declare queue
            queue = await self.channel.declare_queue(
                "webhook_processing",
                durable=True
            )
            
            # Start consuming
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        await self._process_message(json.loads(message.body))
                        
                    if not self.running:
                        break
                        
        except Exception as e:
            log.error(f"RabbitMQ consumer error: {e}")
            if self.running:
                await asyncio.sleep(5)
                await self._start_rabbitmq()
    
    async def _start_sqs(self):
        """Start SQS consumer"""
        while self.running:
            try:
                response = self.sqs_client.receive_message(
                    QueueUrl=settings.sqs_queue_url,
                    MaxNumberOfMessages=1,
                    WaitTimeSeconds=20
                )
                
                if 'Messages' in response:
                    for message in response['Messages']:
                        await self._process_message(json.loads(message['Body']))
                        
                        # Delete message after processing
                        self.sqs_client.delete_message(
                            QueueUrl=settings.sqs_queue_url,
                            ReceiptHandle=message['ReceiptHandle']
                        )
                        
            except Exception as e:
                log.error(f"SQS consumer error: {e}")
                await asyncio.sleep(5)
    
    async def _process_message(self, message: Dict[str, Any]):
        """Process a queue message"""
        try:
            event_type = message.get("event_type")
            session_id = message.get("session_id")
            data = message.get("data", {})
            
            log.info(f"Processing {event_type} event for session {session_id}")
            
            # Get session context
            context = await self.session_manager.get_session_context(session_id)
            if not context:
                log.error(f"Session {session_id} not found")
                return
            
            # Route to appropriate handler
            if event_type == "pipeline_failed":
                await self.handle_pipeline_failure(session_id, context, data)
            elif event_type == "pipeline_success":
                await self.handle_pipeline_success(session_id, context, data)
            elif event_type == "quality_failed":
                await self.analyze_quality_issues(session_id, context, data)
            else:
                log.warning(f"Unknown event type: {event_type}")
                
        except Exception as e:
            log.error(f"Error processing message: {e}")
    
    async def handle_pipeline_failure(
        self,
        session_id: str,
        context: Any,
        data: Dict[str, Any]
    ):
        """Handle pipeline failure analysis"""
        try:
            # Check if quality gate failed in logs
            if await self.check_quality_gate_in_logs(context):
                # Update session type to quality
                await self.session_manager.update_session_metadata(
                    session_id,
                    {"session_type": "quality", "quality_gate_failed": True}
                )
                
                # Run quality analysis
                await self.analyze_quality_from_pipeline(session_id, context, data)
            else:
                # Run pipeline failure analysis
                result = await self.pipeline_agent.analyze_failure(context)
                
                # Store analysis result
                await self.session_manager.update_session_metadata(
                    session_id,
                    {"analysis_result": result, "analysis_completed": True}
                )
                
                # Store in vector DB for future reference
                await self.vector_store.store_analysis(
                    session_id=session_id,
                    project_id=context.project_id,
                    analysis_type="pipeline_failure",
                    error_signature=self._extract_error_signature(result),
                    solution=result.get("solution"),
                    metadata=data
                )
                
        except Exception as e:
            log.error(f"Pipeline failure analysis failed: {e}")
            await self.session_manager.update_session_metadata(
                session_id,
                {"analysis_error": str(e), "status": "failed"}
            )
    
    async def handle_pipeline_success(
        self,
        session_id: str,
        context: Any,
        data: Dict[str, Any]
    ):
        """Handle successful pipeline - store fix in vector DB"""
        try:
            # Get the fix that was applied
            session = await self.session_manager.get_session(session_id)
            fix_data = session.get("applied_fix")
            
            if fix_data:
                # Store successful fix in vector DB
                await self.vector_store.store_successful_fix(
                    session_id=session_id,
                    project_id=context.project_id,
                    fix_type="pipeline",
                    problem_description=fix_data.get("problem"),
                    solution=fix_data.get("solution"),
                    files_changed=fix_data.get("files_changed", []),
                    metadata={
                        "pipeline_id": context.pipeline_id,
                        "branch": context.branch,
                        "fixed_at": datetime.utcnow().isoformat()
                    }
                )
                
                log.info(f"Stored successful fix for session {session_id}")
                
                # Update session status
                await self.session_manager.update_session_metadata(
                    session_id,
                    {"status": "fixed", "fixed_at": datetime.utcnow()}
                )
                
        except Exception as e:
            log.error(f"Failed to store successful fix: {e}")
    
    async def analyze_quality_issues(
        self,
        session_id: str,
        context: Any,
        data: Dict[str, Any]
    ):
        """Analyze quality issues"""
        try:
            # Run quality analysis
            result = await self.quality_agent.analyze_quality_issues(context)
            
            # Store analysis result
            await self.session_manager.update_session_metadata(
                session_id,
                {"analysis_result": result, "analysis_completed": True}
            )
            
            # Store in vector DB
            await self.vector_store.store_analysis(
                session_id=session_id,
                project_id=context.project_id,
                analysis_type="quality_issues",
                error_signature=self._extract_quality_signature(result),
                solution=result.get("solution"),
                metadata=data
            )
            
        except Exception as e:
            log.error(f"Quality analysis failed: {e}")
            await self.session_manager.update_session_metadata(
                session_id,
                {"analysis_error": str(e), "status": "failed"}
            )
    
    async def analyze_quality_from_pipeline(
        self,
        session_id: str,
        context: Any,
        data: Dict[str, Any]
    ):
        """Analyze quality issues found in pipeline logs"""
        # Similar to analyze_quality_issues but with pipeline context
        await self.analyze_quality_issues(session_id, context, data)
    
    async def check_quality_gate_in_logs(self, context: Any) -> bool:
        """Check if quality gate failed in pipeline logs"""
        try:
            # Get pipeline logs
            logs = await self.pipeline_agent.get_pipeline_logs(
                context.project_id,
                context.pipeline_id
            )
            
            # Check for quality gate failure indicators
            quality_indicators = [
                "Quality Gate failed",
                "SonarQube analysis failed",
                "Code coverage below threshold",
                "Too many code smells",
                "Security hotspots detected"
            ]
            
            for indicator in quality_indicators:
                if indicator.lower() in logs.lower():
                    return True
                    
            return False
            
        except Exception as e:
            log.error(f"Failed to check quality gate: {e}")
            return False
    
    def _extract_error_signature(self, analysis_result: Dict) -> str:
        """Extract error signature from analysis"""
        # Extract key error patterns for similarity matching
        error = analysis_result.get("error", "")
        failed_stage = analysis_result.get("failed_stage", "")
        return f"{failed_stage}:{error[:200]}"
    
    def _extract_quality_signature(self, analysis_result: Dict) -> str:
        """Extract quality issue signature"""
        issues = analysis_result.get("issues", [])
        if issues:
            return f"quality:{issues[0].get('type', '')}:{issues[0].get('message', '')[:100]}"
        return "quality:unknown"
    
    async def stop(self):
        """Stop queue processor"""
        self.running = False
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
        log.info("Queue processor stopped")