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
from services.session_continuity import SessionContinuityManager
# SupervisorAgent will handle intelligent delegation - no need for direct agent imports

class QueueProcessor:
    """Process webhook events from message queue"""
    
    def __init__(self):
        self.session_manager = SessionManager()
        self.session_continuity = SessionContinuityManager(self.session_manager)
        # SupervisorAgent handles intelligent delegation - no hardcoded agent instances needed
        # self.vector_store = VectorStore()  # To be implemented
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
            
            # Handle fix branch events first (they have real session IDs but special handling)
            if event_type.startswith("fix_branch_"):
                await self.handle_fix_branch_event(session_id, event_type, data)
                return
            
            # Handle old-style merge request events differently - they don't have real session IDs
            if event_type.startswith("merge_request_"):
                await self.handle_merge_request_event(session_id, None, data)
                return
            
            # Get session context for real analysis sessions
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
    
    async def handle_fix_branch_event(self, session_id: str, event_type: str, data: Dict[str, Any]):
        """Handle fix branch events from webhook-handler"""
        try:
            # Get session context
            context = await self.session_manager.get_session_context(session_id)
            if not context:
                log.error(f"Session {session_id} not found for fix branch event")
                return
            
            log.info(f"Processing fix branch event {event_type} for session {session_id}")
            
            if event_type.startswith("fix_branch_pipeline_"):
                await self.handle_fix_branch_pipeline_event(session_id, context, data)
            elif event_type.startswith("fix_branch_mr_"):
                await self.handle_fix_branch_mr_event(session_id, context, data)
            else:
                log.warning(f"Unknown fix branch event type: {event_type}")
                
        except Exception as e:
            log.error(f"Error handling fix branch event: {e}")
    
    async def handle_fix_branch_pipeline_event(self, session_id: str, context: Any, data: Dict[str, Any]):
        """Handle pipeline results for fix branches"""
        try:
            pipeline_status = data.get("pipeline_status")
            branch_name = data.get("branch_name")
            pipeline_id = data.get("pipeline_id")
            project_id = data.get("project_id")
            
            log.info(f"Fix branch pipeline {pipeline_status} for session {session_id}, branch {branch_name}")
            
            # Use session manager's comprehensive fix branch handling
            if pipeline_status == "success":
                # Use fix iteration handler for success handling too
                from services.fix_iteration_handler import FixIterationHandler
                fix_handler = FixIterationHandler()
                
                # Extract session ID from the branch name
                from utils.branch_naming import safe_extract_session_id
                session_id = safe_extract_session_id(branch_name)
                
                if session_id:
                    # Build webhook data for the handler
                    webhook_data = {
                        "object_attributes": {
                            "id": pipeline_id,
                            "status": "success",
                            "web_url": data.get("pipeline_url")
                        }
                    }
                    
                    result = await fix_handler.handle_fix_branch_success(
                        session_id, branch_name, pipeline_id, webhook_data
                    )
                    log.info(f"Fix iteration handler success result: {result}")
                else:
                    # Fallback to old method if session ID extraction fails
                    await self.session_manager.handle_pipeline_success_on_fix_branch(
                        project_id, branch_name, pipeline_id
                    )
            elif pipeline_status == "failed":
                # Use fix iteration handler for automatic iteration
                from services.fix_iteration_handler import FixIterationHandler
                fix_handler = FixIterationHandler()
                
                # Extract session ID from the branch name
                from utils.branch_naming import safe_extract_session_id
                session_id = safe_extract_session_id(branch_name)
                
                if session_id:
                    # Build webhook data for the handler
                    webhook_data = {
                        "object_attributes": {
                            "id": pipeline_id,
                            "status": "failed",
                            "web_url": data.get("pipeline_url")
                        },
                        "builds": data.get("builds", [])
                    }
                    
                    result = await fix_handler.handle_fix_branch_failure(
                        session_id, branch_name, pipeline_id, webhook_data
                    )
                    log.info(f"Fix iteration handler result: {result}")
                else:
                    # Fallback to old method if session ID extraction fails
                    error_details = self._extract_pipeline_error_details(data)
                    await self.session_manager.handle_pipeline_failure_on_fix_branch(
                        project_id, branch_name, error_details
                    )
                
        except Exception as e:
            log.error(f"Error handling fix branch pipeline event: {e}")
    
    async def handle_fix_branch_mr_event(self, session_id: str, context: Any, data: Dict[str, Any]):
        """Handle merge request results for fix branches"""
        try:
            outcome = data.get("outcome")
            branch_name = data.get("branch_name")
            mr_iid = data.get("mr_iid")
            webhook_data = data.get("webhook_data", {})
            mr_attributes = webhook_data.get("object_attributes", {})
            
            log.info(f"Fix branch MR {outcome} for session {session_id}, branch {branch_name}")
            
            # Update fix attempt with MR information
            fix_attempts = await self.session_manager.get_fix_attempts(session_id)
            for attempt in fix_attempts:
                if (attempt.get('branch_name', '').strip() == branch_name.strip() and 
                    attempt.get('status') == 'pending'):
                    
                    mr_url = mr_attributes.get("url")
                    
                    # Update attempt with MR details
                    await self.session_manager.update_fix_attempt(
                        session_id,
                        attempt['attempt_number'],
                        'pending',  # Keep pending until pipeline result
                        str(mr_iid),
                        mr_url
                    )
                    
                    # Add informational message about MR status
                    if outcome == "merged":
                        await self.session_manager.add_message(
                            session_id,
                            "assistant",
                            f"🔀 **Merge Request Merged**\n\n"
                            f"Fix attempt #{attempt['attempt_number']} has been merged into the target branch.\n"
                            f"Waiting for pipeline results to confirm the fix..."
                        )
                    elif outcome == "closed":
                        await self.session_manager.update_fix_attempt(
                            session_id,
                            attempt['attempt_number'],
                            'failed',
                            str(mr_iid),
                            mr_url,
                            "Merge request was closed without merging"
                        )
                        await self.session_manager.add_message(
                            session_id,
                            "assistant",
                            f"❌ **Merge Request Closed**\n\n"
                            f"Fix attempt #{attempt['attempt_number']} was closed without merging.\n"
                            f"You can create a new fix attempt."
                        )
                    break
                    
        except Exception as e:
            log.error(f"Error handling fix branch MR event: {e}")
    
    def _extract_pipeline_error_details(self, data: Dict[str, Any]) -> str:
        """Extract pipeline error details from webhook data"""
        try:
            webhook_data = data.get("webhook_data", {})
            builds = webhook_data.get("builds", [])
            failed_jobs = [job for job in builds if job.get("status") == "failed"]
            
            if failed_jobs:
                # Get the most recent failure
                failed_jobs.sort(key=lambda x: x.get("finished_at", ""), reverse=True)
                first_failed = failed_jobs[0]
                
                error_details = f"Job '{first_failed.get('name')}' failed in stage '{first_failed.get('stage')}'"
                if first_failed.get("failure_reason"):
                    error_details += f": {first_failed.get('failure_reason')}"
                
                return error_details
            else:
                return "Pipeline failed - no specific job failure details available"
                
        except Exception as e:
            log.error(f"Error extracting pipeline error details: {e}")
            return "Pipeline failed"
    
    async def _mark_fix_attempt_pipeline_success(self, session_id: str, branch_name: str, pipeline_id: str):
        """Mark fix attempt pipeline as successful"""
        try:
            await self.session_manager.update_fix_attempt_status(
                session_id,
                branch_name,
                "pipeline_success",
                {
                    "pipeline_id": pipeline_id,
                    "pipeline_status": "success",
                    "pipeline_completed_at": datetime.now().isoformat()
                }
            )
            log.info(f"Marked fix attempt pipeline success: {branch_name} for session {session_id}")
        except Exception as e:
            log.error(f"Error marking fix attempt pipeline success: {e}")
    
    async def _mark_fix_attempt_pipeline_failed(self, session_id: str, branch_name: str, pipeline_id: str):
        """Mark fix attempt pipeline as failed"""
        try:
            await self.session_manager.update_fix_attempt_status(
                session_id,
                branch_name,
                "pipeline_failed",
                {
                    "pipeline_id": pipeline_id,
                    "pipeline_status": "failed",
                    "pipeline_completed_at": datetime.now().isoformat()
                }
            )
            log.info(f"Marked fix attempt pipeline failed: {branch_name} for session {session_id}")
        except Exception as e:
            log.error(f"Error marking fix attempt pipeline failed: {e}")
    
    async def _mark_fix_attempt_mr_success(self, session_id: str, branch_name: str, mr_iid: str):
        """Mark fix attempt MR as merged successfully"""
        try:
            await self.session_manager.update_fix_attempt_status(
                session_id,
                branch_name,
                "mr_merged",
                {
                    "merge_request_id": mr_iid,
                    "mr_status": "merged",
                    "mr_completed_at": datetime.now().isoformat(),
                    "fix_successful": True
                }
            )
            log.info(f"Marked fix attempt MR merged: {branch_name} for session {session_id}")
        except Exception as e:
            log.error(f"Error marking fix attempt MR success: {e}")
    
    async def _mark_fix_attempt_mr_failed(self, session_id: str, branch_name: str, mr_iid: str):
        """Mark fix attempt MR as closed without merging"""
        try:
            await self.session_manager.update_fix_attempt_status(
                session_id,
                branch_name,
                "mr_closed",
                {
                    "merge_request_id": mr_iid,
                    "mr_status": "closed",
                    "mr_completed_at": datetime.now().isoformat(),
                    "fix_successful": False
                }
            )
            log.info(f"Marked fix attempt MR closed: {branch_name} for session {session_id}")
        except Exception as e:
            log.error(f"Error marking fix attempt MR failed: {e}")
    
    async def handle_pipeline_failure(
        self,
        session_id: str,
        context: Any,
        data: Dict[str, Any]
    ):
        """Handle pipeline failure analysis using AWS Strands SupervisorAgent coordination"""
        try:
            webhook_data = data.get("webhook_data", {})
            project_id = context.project_id
            pipeline_id = context.pipeline_id
            
            log.info(f"Processing pipeline failure with SupervisorAgent for session {session_id}")
            
            # Use SupervisorAgent for intelligent coordination following AWS Agent Squad patterns
            from agents.supervisor_agent import supervisor_agent
            
            # Build comprehensive failure context for the supervisor
            failure_context = {
                "event_type": "pipeline_failure",
                "pipeline_id": pipeline_id,
                "project_id": project_id,
                "session_context": {
                    "session_id": session_id,
                    "project_name": getattr(context, 'project_name', 'unknown'),
                    "sonarqube_key": getattr(context, 'sonarqube_key', None),
                    "original_failure_type": "pipeline"
                },
                "webhook_indicators": {
                    "quality_detected_by_handler": data.get("quality_failure_detected", False),
                    "pipeline_stage": webhook_data.get("object_attributes", {}).get("stage", "unknown"),
                    "pipeline_status": webhook_data.get("object_attributes", {}).get("status", "unknown")
                }
            }
            
            # Pre-classify the session type for UI routing
            is_quality_failure = (
                data.get("quality_failure_detected", False) or
                "quality" in webhook_data.get("object_attributes", {}).get("stage", "").lower() or
                "sonar" in webhook_data.get("object_attributes", {}).get("stage", "").lower()
            )
            
            if is_quality_failure:
                # Mark this as a quality session for proper UI routing
                await self.session_manager.update_session_metadata(
                    session_id,
                    {"session_type": "quality", "quality_gate_failed": True}
                )
                log.info(f"Marked session {session_id} as quality session for UI routing")
            else:
                # Mark as pipeline session
                await self.session_manager.update_session_metadata(
                    session_id,
                    {"session_type": "pipeline"}
                )
                log.info(f"Marked session {session_id} as pipeline session for UI routing")
            
            log.info(f"Delegating to SupervisorAgent for intelligent failure analysis coordination")
            
            # Let the SupervisorAgent coordinate the analysis using agent-as-tools architecture
            result = await supervisor_agent.coordinate_failure_analysis(
                session_id,
                project_id,
                webhook_data,
                failure_context
            )
            
            # Store the comprehensive analysis result
            await self.session_manager.update_session_metadata(
                session_id,
                {"analysis_result": result, "analysis_completed": True, "coordinated_by": "supervisor_agent"}
            )
            
            log.info(f"SupervisorAgent coordination completed for session {session_id}: {result[:200]}...")
                
        except Exception as e:
            log.error(f"SupervisorAgent pipeline failure coordination failed: {e}")
            await self.session_manager.update_session_metadata(
                session_id,
                {"analysis_error": str(e), "status": "failed", "coordination_failed": True}
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
                # TODO: Store successful fix in vector store
                # await self.vector_store.store_successful_fix(
                #     session_id=session_id,
                #     project_id=context.project_id,
                #     fix_type="merge_request",
                #     mr_url=merge_request.get("web_url"),
                #     error_signature=self._extract_error_signature(session_data)
                # )
                
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
        """Analyze quality issues with session continuity - following working version pattern"""
        try:
            webhook_data = data.get("webhook_data", {})
            project_id = context.project_id
            
            # Check for session continuity - should we continue existing session?
            should_continue, existing_session_id = await self.session_continuity.should_continue_session(
                project_id, webhook_data, context
            )
            
            if should_continue and existing_session_id != session_id:
                log.info(f"Session continuity detected for quality analysis: continuing session {existing_session_id} instead of {session_id}")
                
                # Create agent handoff context
                handoff_context = await self.session_continuity.create_handoff_context(
                    existing_session_id,
                    session_id,
                    "pipeline_agent",
                    "quality_agent",
                    f"Quality gate failure on fix branch",
                    project_id,
                    context.pipeline_id,
                    webhook_data.get("ref", "").replace("refs/heads/", "")
                )
                
                # Record the handoff
                await self.session_continuity.record_agent_handoff(
                    existing_session_id,
                    "pipeline_agent",
                    "quality_agent",
                    f"Fix branch quality gate failure - pipeline {context.pipeline_id}",
                    handoff_context
                )
                
                # Update the session_id to continue the existing session
                session_id = existing_session_id
                context = await self.session_manager.get_session_context(session_id)
            
            project_key = context.sonarqube_key or f"{context.project_name}".replace("/", "_")
            
            # Check for infrastructure issues first
            infrastructure_alerts = await self.session_continuity.detect_infrastructure_issues(
                project_id, project_key
            )
            
            if infrastructure_alerts:
                log.warning(f"Infrastructure issues detected for session {session_id}: {infrastructure_alerts}")
                # Store infrastructure alerts in session
                await self.session_manager.update_session_metadata(
                    session_id,
                    {"infrastructure_alerts": infrastructure_alerts}
                )
            
            # Map SonarQube project key to GitLab project ID
            from api.webhooks import get_gitlab_project_id
            gitlab_project_id = await get_gitlab_project_id(project_key)
            if not gitlab_project_id:
                log.error(f"Could not find GitLab project for SonarQube key: {project_key}")
                gitlab_project_id = context.project_id  # Fall back to original value
            
            log.info(f"Processing quality failure for project {project_key}, session {session_id}")
            
            # Following working version: fetch SonarQube data first, then provide to agent
            try:
                from tools.sonarqube import get_project_issues, get_project_metrics, get_project_quality_gate_status
                
                # Get quality gate status
                quality_status = await get_project_quality_gate_status(project_key)
                
                # Check if there are actual quality issues or just no analysis
                project_status = quality_status.get("projectStatus", {})
                if project_status.get("status") == "NONE" or not project_status:
                    log.warning(f"No quality gate configured or no analysis for {project_key}")
                    result = f"## ⚠️ SonarQube Analysis Issue\n\nNo SonarQube analysis results found for project '{project_key}'. This appears to be a pipeline configuration issue, not a code quality issue."
                    
                    # Include infrastructure alerts if detected
                    if infrastructure_alerts:
                        result += f"\n\n**Infrastructure Issues Detected:**\n{infrastructure_alerts}"
                else:
                    # Get issue counts by type
                    bugs = await get_project_issues(project_key, types="BUG", limit=500)
                    vulnerabilities = await get_project_issues(project_key, types="VULNERABILITY", limit=500) 
                    code_smells = await get_project_issues(project_key, types="CODE_SMELL", limit=500)
                    
                    # Get project metrics
                    try:
                        metrics = await get_project_metrics(project_key)
                    except Exception as e:
                        log.warning(f"Could not fetch metrics for {project_key}: {e}")
                        metrics = {}
                    
                    # Calculate counts
                    total_issues = len(bugs) + len(vulnerabilities) + len(code_smells)
                    critical_count = sum(1 for b in bugs if b.get("severity") in ["CRITICAL", "BLOCKER"])
                    critical_count += sum(1 for v in vulnerabilities if v.get("severity") in ["CRITICAL", "BLOCKER"])
                    major_count = sum(1 for b in bugs if b.get("severity") == "MAJOR")
                    major_count += sum(1 for v in vulnerabilities if v.get("severity") == "MAJOR")
                    
                    # Prepare enhanced webhook data with quality information (like working version)
                    enhanced_webhook_data = {
                        **webhook_data,
                        "qualityGate": project_status,
                        "sonarqube_data": {
                            "bugs": bugs,
                            "vulnerabilities": vulnerabilities,
                            "code_smells": code_smells,
                            "metrics": metrics,
                            "total_issues": total_issues,
                            "critical_issues": critical_count,
                            "major_issues": major_count
                        }
                    }
                    
                    log.info(f"Enhanced webhook data with SonarQube results: {total_issues} total issues")
                    
                    # Log the raw data we're working with
                    log.info(f"Raw data: total_issues={total_issues} (type: {type(total_issues)})")
                    log.info(f"Raw data: bugs={len(bugs)}, vulnerabilities={len(vulnerabilities)}, code_smells={len(code_smells)}")
                    log.info(f"Raw data: critical_count={critical_count}, major_count={major_count}")
                    log.info(f"Raw metrics: {metrics}")
                    
                    # Update session with quality metrics FIRST (following GitHub repository pattern)
                    metrics_to_update = {
                        "total_issues": total_issues,
                        "bug_count": len(bugs),
                        "vulnerability_count": len(vulnerabilities),
                        "code_smell_count": len(code_smells),
                        "critical_issues": critical_count,
                        "major_issues": major_count,
                        "coverage": metrics.get("coverage", "0"),
                        "duplicated_lines_density": metrics.get("duplicated_lines_density", "0"),
                        "reliability_rating": metrics.get("reliability_rating", "E"),
                        "security_rating": metrics.get("security_rating", "E"),
                        "maintainability_rating": metrics.get("maintainability_rating", "E")
                    }
                    
                    log.info(f"Metrics to update: {metrics_to_update}")
                    
                    await self.session_manager.update_quality_metrics(session_id, metrics_to_update)
                    log.info(f"Quality metrics successfully updated for session {session_id}")
                    
                    # Prepare enhanced webhook data with quality information
                    enhanced_webhook_data = {
                        **webhook_data,
                        "qualityGate": project_status,
                        "sonarqube_data": {
                            "bugs": bugs,
                            "vulnerabilities": vulnerabilities,
                            "code_smells": code_smells,
                            "metrics": metrics,
                            "total_issues": total_issues,
                            "critical_issues": critical_count,
                            "major_issues": major_count
                        }
                    }
                    
                    # Run quality analysis (using working version signature with enhanced data)
                    result = await self.quality_agent.analyze_quality_issues(
                        session_id,
                        project_key,
                        gitlab_project_id,
                        enhanced_webhook_data
                    )
                
            except Exception as e:
                log.error(f"Failed to fetch SonarQube data: {e}")
                # Fall back to original analysis with original data
                result = await self.quality_agent.analyze_quality_issues(
                    session_id,
                    project_key,
                    gitlab_project_id,
                    webhook_data
                )
            
            # Ensure we have a valid result
            log.info(f"Quality agent returned result type: {type(result)}")
            log.info(f"Quality agent result preview: {str(result)[:200]}...")
            
            if not result:
                result_str = "❌ Analysis failed to produce results. Please check the logs for more details."
            elif isinstance(result, dict):
                # Handle dict response from agent - this should not happen after our fix
                log.warning(f"Agent returned dict instead of string: {result}")
                result_str = str(result)
            else:
                result_str = str(result)
            
            # Convert to string and check if empty
            if not result_str or result_str.strip() == "" or result_str.strip() == "None":
                result_str = "❌ Analysis failed to produce results. Please check the logs for more details."
            
            # Include infrastructure alerts in the result if detected
            if infrastructure_alerts and "SonarQube Analysis Issue" not in result_str:
                result_str += f"\n\n---\n\n**⚠️ Infrastructure Issues Detected:**\n{infrastructure_alerts}"
            
            log.info(f"Final result string length: {len(result_str)}")
            log.info(f"Final result preview: {result_str[:200]}...")
            
            # Store analysis result with conversation message
            await self.session_manager.update_session_metadata(
                session_id,
                {"analysis_result": result_str, "analysis_completed": True}
            )
            
            # Add the analysis as the first assistant message in conversation
            await self.session_manager.add_message(session_id, "assistant", result_str)
            
            log.info(f"Quality analysis completed and stored for session {session_id}")
            
        except Exception as e:
            log.error(f"Quality analysis failed: {e}")
            error_message = f"❌ Quality analysis failed: {str(e)}"
            await self.session_manager.update_session_metadata(
                session_id,
                {"analysis_error": str(e), "status": "failed"}
            )
            # Store error message in conversation
            await self.session_manager.add_message(session_id, "assistant", error_message)
    
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
            # Import pipeline agent dynamically when needed
            from agents.pipeline_agent import pipeline_agent
            
            # Get pipeline logs
            logs = await pipeline_agent.get_pipeline_logs(
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
    
    async def handle_merge_request_event(
        self,
        fake_session_id: str,
        context: Any,
        data: Dict[str, Any]
    ):
        """Handle merge request events for session tracking"""
        try:
            event_type = data.get("event_type")
            mr_action = data.get("mr_action")
            mr_iid = data.get("mr_iid")
            project_id = data.get("project_id")
            webhook_data = data.get("webhook_data", {})
            
            log.info(f"Processing MR event: {mr_action} for MR !{mr_iid} in project {project_id}")
            
            # Extract MR details to find the real session
            mr_attributes = webhook_data.get("object_attributes", {})
            source_branch = mr_attributes.get("source_branch", "")
            target_branch = mr_attributes.get("target_branch", "")
            mr_url = mr_attributes.get("url", "")
            
            # Find the real session that might have created this MR
            real_session = await self._find_session_by_mr_details(project_id, source_branch, mr_url, mr_iid)
            
            if real_session:
                log.info(f"Found matching session {real_session['id']} for MR !{mr_iid}")
                
                # Handle different merge request actions with the real session
                if mr_action == "merge":
                    await self._handle_merge_request_merged(real_session["id"], real_session, data)
                elif mr_action == "close":
                    await self._handle_merge_request_closed(real_session["id"], real_session, data)
                elif mr_action in ["open", "update"]:
                    await self._handle_merge_request_opened_updated(real_session["id"], real_session, data)
                else:
                    log.info(f"MR action '{mr_action}' not requiring special handling")
            else:
                log.info(f"No matching session found for MR !{mr_iid} in project {project_id}")
                
        except Exception as e:
            log.error(f"Error handling MR event: {e}")
    
    async def _find_session_by_mr_details(self, project_id: str, source_branch: str, mr_url: str, mr_iid: str):
        """Find session by MR details (branch name, URL, etc.)"""
        try:
            # Get all active sessions for this project
            all_sessions = await self.session_manager.get_active_sessions()
            project_sessions = [s for s in all_sessions if s.get("project_id") == project_id]
            
            # Try multiple correlation methods
            
            # Method 1: Find by MR URL
            if mr_url:
                for session in project_sessions:
                    if session.get("merge_request_url") == mr_url:
                        return session
            
            # Method 2: Find by branch name using our naming convention
            if source_branch:
                from api.webhooks import find_session_by_branch
                session = find_session_by_branch(source_branch, project_sessions)
                if session:
                    return session
            
            # Method 3: Find by fix attempts with matching MR IID
            for session in project_sessions:
                fix_attempts = await self.session_manager.get_fix_attempts(session["id"])
                for attempt in fix_attempts:
                    if attempt.get("merge_request_id") == mr_iid:
                        return session
            
            return None
            
        except Exception as e:
            log.error(f"Error finding session by MR details: {e}")
            return None
    
    async def _handle_merge_request_merged(self, session_id: str, session_context: Any, data: Dict[str, Any]):
        """Handle when merge request is merged successfully"""
        try:
            webhook_data = data.get("webhook_data", {})
            mr_attributes = webhook_data.get("object_attributes", {})
            mr_iid = mr_attributes.get("iid")
            source_branch = mr_attributes.get("source_branch")
            merge_commit_sha = mr_attributes.get("merge_commit_sha")
            
            log.info(f"MR !{mr_iid} merged successfully for session {session_id}")
            
            # Update session with merge status
            await self.session_manager.update_session_status(
                session_id,
                "merge_request_merged",
                {
                    "merge_request_id": mr_iid,
                    "source_branch": source_branch,
                    "merge_commit_sha": merge_commit_sha,
                    "merged_at": mr_attributes.get("updated_at")
                }
            )
            
            # Mark fix attempt as successful if this was a fix branch
            if source_branch and any(prefix in source_branch for prefix in ["fix_", "pipeline_fix_", "quality_fix_"]):
                await self._mark_fix_attempt_success(session_id, mr_iid, source_branch)
                
        except Exception as e:
            log.error(f"Error handling merged MR: {e}")
    
    async def _handle_merge_request_closed(self, session_id: str, session_context: Any, data: Dict[str, Any]):
        """Handle when merge request is closed without merging"""
        try:
            webhook_data = data.get("webhook_data", {})
            mr_attributes = webhook_data.get("object_attributes", {})
            mr_iid = mr_attributes.get("iid")
            source_branch = mr_attributes.get("source_branch")
            state = mr_attributes.get("state")
            
            log.info(f"MR !{mr_iid} closed (state: {state}) for session {session_id}")
            
            # Update session with closure status
            await self.session_manager.update_session_status(
                session_id,
                "merge_request_closed",
                {
                    "merge_request_id": mr_iid,
                    "source_branch": source_branch,
                    "state": state,
                    "closed_at": mr_attributes.get("updated_at")
                }
            )
            
            # Mark fix attempt as failed if this was a fix branch
            if source_branch and any(prefix in source_branch for prefix in ["fix_", "pipeline_fix_", "quality_fix_"]):
                await self._mark_fix_attempt_failed(session_id, mr_iid, source_branch, "merge_request_closed")
                
        except Exception as e:
            log.error(f"Error handling closed MR: {e}")
    
    async def _handle_merge_request_opened_updated(self, session_id: str, session_context: Any, data: Dict[str, Any]):
        """Handle when merge request is opened or updated"""
        try:
            webhook_data = data.get("webhook_data", {})
            mr_attributes = webhook_data.get("object_attributes", {})
            mr_iid = mr_attributes.get("iid")
            source_branch = mr_attributes.get("source_branch")
            mr_action = data.get("mr_action")
            
            log.info(f"MR !{mr_iid} {mr_action} for session {session_id}")
            
            # Update session with MR details
            await self.session_manager.update_session_status(
                session_id,
                f"merge_request_{mr_action}",
                {
                    "merge_request_id": mr_iid,
                    "source_branch": source_branch,
                    "merge_request_url": mr_attributes.get("url"),
                    "title": mr_attributes.get("title"),
                    "description": mr_attributes.get("description"),
                    f"{mr_action}_at": mr_attributes.get("updated_at")
                }
            )
            
        except Exception as e:
            log.error(f"Error handling {data.get('mr_action')} MR: {e}")
    
    async def _mark_fix_attempt_success(self, session_id: str, mr_iid: str, branch_name: str):
        """Mark a fix attempt as successful"""
        try:
            await self.session_manager.update_fix_attempt_status(
                session_id,
                branch_name,
                "success",
                {
                    "merge_request_id": mr_iid,
                    "result": "merged_successfully",
                    "completed_at": datetime.now().isoformat()
                }
            )
            log.info(f"Marked fix attempt {branch_name} as successful for session {session_id}")
        except Exception as e:
            log.error(f"Error marking fix attempt success: {e}")
    
    async def _mark_fix_attempt_failed(self, session_id: str, mr_iid: str, branch_name: str, reason: str):
        """Mark a fix attempt as failed"""
        try:
            await self.session_manager.update_fix_attempt_status(
                session_id,
                branch_name,
                "failed",
                {
                    "merge_request_id": mr_iid,
                    "result": reason,
                    "completed_at": datetime.now().isoformat()
                }
            )
            log.info(f"Marked fix attempt {branch_name} as failed for session {session_id}: {reason}")
        except Exception as e:
            log.error(f"Error marking fix attempt failed: {e}")
    
    async def stop(self):
        """Stop queue processor"""
        self.running = False
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
        log.info("Queue processor stopped")