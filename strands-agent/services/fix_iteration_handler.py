"""Fix iteration handler for managing failed fix attempts"""

import asyncio, os
from typing import Dict, Any, Optional, List
from datetime import datetime
from utils.logger import log
from db.session_manager import SessionManager

class FixIterationHandler:
    """Handles failed fix attempts and generates improved solutions"""
    
    def __init__(self):
        self.session_manager = SessionManager()
        self.max_attempts = int(os.getenv('MAX_FIX_ATTEMPTS', '3'))
        
    async def handle_fix_branch_failure(
        self,
        session_id: str,
        branch_name: str,
        pipeline_id: str,
        webhook_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle a failed pipeline on a fix branch"""
        
        try:
            log.info(f"Handling fix branch failure for session {session_id}, branch {branch_name}")
            
            # Get session data
            session = await self.session_manager.get_session(session_id)
            if not session:
                log.error(f"Session {session_id} not found")
                return {"status": "error", "message": "Session not found"}
            
            # Get or initialize fix attempts
            fix_attempts = session.get('fix_attempts', [])
            
            # Check if we already have an attempt for this pipeline_id to avoid duplicates
            existing_attempt = next((attempt for attempt in fix_attempts 
                                   if attempt.get('pipeline_id') == pipeline_id), None)
            if existing_attempt:
                log.warning(f"Pipeline {pipeline_id} already has a recorded attempt {existing_attempt.get('attempt')}, skipping duplicate")
                return {
                    "status": "duplicate_attempt",
                    "attempt": existing_attempt.get('attempt'),
                    "message": f"Attempt for pipeline {pipeline_id} already recorded"
                }
            
            current_attempt = len(fix_attempts) + 1
            
            log.debug(f"Current fix attempts for session {session_id}: {len(fix_attempts)}, new attempt: {current_attempt}")
            log.debug(f"Existing fix attempts: {[attempt.get('attempt', 'unknown') for attempt in fix_attempts]}")
            log.debug(f"Pipeline ID for this attempt: {pipeline_id}")
            
            if current_attempt > self.max_attempts:
                log.warning(f"Max attempts ({self.max_attempts}) reached for session {session_id}")
                await self.session_manager.update_session_metadata(
                    session_id,
                    {
                        "status": "max_attempts_reached",
                        "total_attempts": current_attempt - 1,
                        "failed_branch": branch_name
                    }
                )
                return {
                    "status": "max_attempts_reached",
                    "attempts": fix_attempts,
                    "message": f"Maximum fix attempts ({self.max_attempts}) reached"
                }
            
            # Extract failure information
            failed_jobs = self._extract_failed_jobs(webhook_data)
            error_patterns = self._extract_error_patterns(failed_jobs)
            
            # Create fix attempt record
            fix_attempt = {
                "attempt": current_attempt,
                "timestamp": datetime.utcnow().isoformat(),
                "pipeline_id": pipeline_id,
                "branch": branch_name,
                "failed_jobs": failed_jobs,
                "error_patterns": error_patterns,
                "status": "failed"
            }
            
            # Add to attempts list
            fix_attempts.append(fix_attempt)
            
            # Store analysis of why the fix failed
            failure_analysis = {
                "previous_attempt": fix_attempts[-2] if len(fix_attempts) > 1 else None,
                "current_errors": error_patterns,
                "recurring_patterns": self._find_recurring_patterns(fix_attempts),
                "suggested_approach": self._suggest_new_approach(fix_attempts, error_patterns)
            }
            
            # Update session with new attempt data
            log.debug(f"Updating session {session_id} with {len(fix_attempts)} attempts (just added attempt {current_attempt})")
            await self.session_manager.update_session_metadata(
                session_id,
                {
                    "fix_attempts": fix_attempts,
                    "current_attempt": current_attempt,
                    "last_failure_analysis": failure_analysis,
                    "status": "retrying_fix",
                    "failed_branch": branch_name
                }
            )
            
            log.info(f"Recorded fix attempt {current_attempt} for session {session_id} on branch {branch_name}")
            
            # AUTO-RETRY: Trigger next fix attempt if under limit
            if current_attempt < self.max_attempts:
                log.info(f"Auto-triggering retry for session {session_id} (attempt {current_attempt}/{self.max_attempts})")
                await self._trigger_automatic_retry(session_id, failure_analysis, current_attempt)
            else:
                log.warning(f"Max attempts ({self.max_attempts}) reached for session {session_id}, no more retries")
            
            return {
                "status": "retry_needed",
                "attempt": current_attempt,
                "failure_analysis": failure_analysis,
                "previous_attempts": fix_attempts,
                "suggested_approach": failure_analysis['suggested_approach']
            }
            
        except Exception as e:
            log.error(f"Error handling fix branch failure: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def _trigger_automatic_retry(self, session_id: str, failure_analysis: Dict, attempt_number: int):
        """Trigger automatic retry for failed fix attempt"""
        try:
            log.debug(f"Starting automatic retry for session {session_id}, attempt {attempt_number}")
            
            # Get session context
            session = await self.session_manager.get_session(session_id)
            if not session:
                log.error(f"Session {session_id} not found for auto-retry")
                return

            # Dynamically determine agent type based on current failure patterns
            session_type = await self._determine_failure_agent_type(session, failure_analysis)
            
            # Prepare retry message with iteration context
            retry_message = (
                f"The previous fix attempt #{attempt_number} failed. "
                f"Please analyze the latest errors and create another fix targeting the remaining issues. "
                f"This is an iterative fix - build on what was tried before."
            )
            
            log.debug(f"Adding retry message to session {session_id}: {retry_message[:100]}...")
            
            # Add user message for retry
            await self.session_manager.add_message(session_id, "user", retry_message)
            
            # Get conversation history for context
            conversation_history = session.get("conversation_history", [])
            
            log.debug(f"Retrieved {len(conversation_history)} messages from conversation history")
            
            # Get session context for the agent
            from db.models import SessionContext
            context = SessionContext(
                session_id=session_id,
                session_type=session_type,
                project_id=session.get("project_id"),
                project_name=session.get("project_name", "Unknown Project"),
                gitlab_project_id=session.get("gitlab_project_id", session.get("project_id")),
                branch=session.get("branch"),
                pipeline_id=session.get("pipeline_id"),
                job_name=session.get("job_name"),
                failed_stage=session.get("failed_stage")
            )
            
            log.debug(f"Created session context for {session_type} agent")
            
            # Trigger the appropriate agent
            if session_type == "quality":
                log.info(f"Triggering quality agent for retry attempt {attempt_number + 1}")
                from agents.quality_agent import quality_agent
                response = await quality_agent.handle_user_message(
                    session_id, 
                    retry_message,
                    conversation_history,
                    context
                )
            else:
                log.info(f"Triggering pipeline agent for retry attempt {attempt_number + 1}")
                from agents.pipeline_agent import pipeline_agent
                response = await pipeline_agent.handle_user_message(
                    session_id,
                    retry_message,
                    conversation_history, 
                    context
                )
            
            # Extract text from response
            if hasattr(response, 'message'):
                response_text = response.message
            elif isinstance(response, dict) and "content" in response:
                content = response["content"]
                if isinstance(content, list):
                    response_text = content[0].get("text", str(response))
                else:
                    response_text = str(content)
            else:
                response_text = str(response)
            
            log.debug(f"Agent response length: {len(response_text)} characters")
            
            # Store agent response
            await self.session_manager.add_message(session_id, "assistant", response_text)
            
            log.info(f"Auto-retry completed for session {session_id}, attempt {attempt_number + 1}")
            
        except Exception as e:
            log.error(f"Error triggering automatic retry for session {session_id}: {e}", exc_info=True)

    async def handle_failed_fix(
        self,
        session_id: str,
        webhook_data: Dict[str, Any],
        pipeline_status: str = "failed"
    ) -> Dict[str, Any]:
        """Handle a failed fix attempt"""
        
        try:
            # Get session data
            session = await self.session_manager.get_session(session_id)
            if not session:
                log.error(f"Session {session_id} not found")
                return {"status": "error", "message": "Session not found"}
            
            # Get or initialize fix attempts
            fix_attempts = session.get('fix_attempts', [])
            current_attempt = len(fix_attempts) + 1
            
            
            if current_attempt > self.max_attempts:
                log.warning(f"Max attempts ({self.max_attempts}) reached for session {session_id}")
                await self.session_manager.update_session_metadata(
                    session_id,
                    {
                        "status": "max_attempts_reached",
                        "total_attempts": current_attempt - 1
                    }
                )
                return {
                    "status": "max_attempts_reached",
                    "attempts": fix_attempts,
                    "message": f"Maximum fix attempts ({self.max_attempts}) reached"
                }
            
            # Extract failure information
            failed_jobs = self._extract_failed_jobs(webhook_data)
            error_patterns = self._extract_error_patterns(failed_jobs)
            
            # Get enhanced pipeline analysis
            pipeline_analysis = await self._analyze_pipeline_logs_for_context(
                failed_jobs, error_patterns, session
            )
            
            # Create fix attempt record with enhanced analysis
            fix_attempt = {
                "attempt": current_attempt,
                "timestamp": datetime.utcnow().isoformat(),
                "pipeline_id": webhook_data.get('object_attributes', {}).get('id'),
                "branch": webhook_data.get('object_attributes', {}).get('ref'),
                "failed_jobs": failed_jobs,
                "error_patterns": error_patterns,
                "pipeline_analysis": pipeline_analysis,
                "status": pipeline_status
            }
            
            # Add to attempts list
            fix_attempts.append(fix_attempt)
            
            # Store analysis of why the fix failed
            failure_analysis = {
                "previous_attempt": fix_attempts[-2] if len(fix_attempts) > 1 else None,
                "current_errors": error_patterns,
                "pipeline_analysis": pipeline_analysis,
                "recurring_patterns": self._find_recurring_patterns(fix_attempts),
                "suggested_approach": self._suggest_new_approach(fix_attempts, error_patterns)
            }
            
            # Update session with new attempt data
            await self.session_manager.update_session_metadata(
                session_id,
                {
                    "fix_attempts": fix_attempts,
                    "current_attempt": current_attempt,
                    "last_failure_analysis": failure_analysis,
                    "status": "retrying_fix"
                }
            )
            
            log.info(f"Recorded fix attempt {current_attempt} for session {session_id}")
            
            return {
                "status": "retry_needed",
                "attempt": current_attempt,
                "failure_analysis": failure_analysis,
                "previous_attempts": fix_attempts,
                "suggested_approach": failure_analysis['suggested_approach']
            }
            
        except Exception as e:
            log.error(f"Error handling failed fix: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
    
    async def handle_fix_branch_success(
        self,
        session_id: str,
        branch_name: str,
        pipeline_id: str,
        webhook_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle a successful pipeline on a fix branch"""
        
        try:
            log.info(f"Handling fix branch success for session {session_id}, branch {branch_name}")
            
            # Record the successful fix
            result = await self.record_successful_fix(session_id, branch_name, pipeline_id)
            
            if result.get("status") == "success":
                log.info(f"Fix successful for session {session_id} after {result.get('total_attempts', 0)} attempts")
                
                # Optionally notify user about successful fix
                try:
                    success_message = (
                        f"🎉 **Fix Successful!**\n\n"
                        f"The quality fixes have been successfully applied and the pipeline is now passing.\n\n"
                        f"**Summary:**\n"
                        f"- Total fix attempts: {result.get('total_attempts', 1)}\n"
                        f"- Branch: `{branch_name}`\n"
                        f"- Pipeline ID: {pipeline_id}\n\n"
                        f"All quality gates are now passing. The merge request can be safely merged."
                    )
                    
                    # Add success message to conversation - use simple text format
                    await self.session_manager.add_message(session_id, "assistant", success_message)
                    
                except Exception as msg_error:
                    log.warning(f"Could not add success message to session {session_id}: {msg_error}")
            
            return result
            
        except Exception as e:
            log.error(f"Error handling fix branch success: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def record_successful_fix(
        self,
        session_id: str,
        branch_name: str,
        pipeline_id: str
    ) -> Dict[str, Any]:
        """Record a successful fix for learning"""
        
        try:
            session = await self.session_manager.get_session(session_id)
            if not session:
                return {"status": "error", "message": "Session not found"}
            
            fix_attempts = session.get('fix_attempts', [])
            
            success_record = {
                "session_id": session_id,
                "branch": branch_name,
                "pipeline_id": pipeline_id,
                "total_attempts": len(fix_attempts),
                "timestamp": datetime.utcnow().isoformat(),
                "fix_patterns": self._extract_successful_patterns(session)
            }
            
            # Update session status
            await self.session_manager.update_session_metadata(
                session_id,
                {
                    "status": "fix_successful",
                    "successful_branch": branch_name,
                    "success_record": success_record
                }
            )
            
            log.info(f"Recorded successful fix for session {session_id} after {len(fix_attempts)} attempts")
            
            # Store for future learning (could integrate with vector store here)
            await self._store_successful_pattern(success_record)
            
            log.debug(f"Success record details: {success_record}")
            
            return {
                "status": "success",
                "total_attempts": len(fix_attempts),
                "success_record": success_record
            }
            
        except Exception as e:
            log.error(f"Error recording successful fix: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
    
    def _extract_failed_jobs(self, webhook_data: Dict) -> List[Dict]:
        """Extract failed job information from webhook"""
        failed_jobs = []
        
        builds = webhook_data.get('builds', [])
        log.debug(f"Extracting failed jobs from {len(builds)} builds")
        
        for build in builds:
            if build.get('status') == 'failed':
                failed_job = {
                    'name': build.get('name'),
                    'stage': build.get('stage'),
                    'failure_reason': build.get('failure_reason'),
                    'id': build.get('id')
                }
                failed_jobs.append(failed_job)
                log.debug(f"Found failed job: {failed_job['name']} in stage {failed_job['stage']}")
        
        log.debug(f"Extracted {len(failed_jobs)} failed jobs")
        return failed_jobs
    
    def _extract_error_patterns(self, failed_jobs: List[Dict]) -> List[str]:
        """Extract error patterns from failed jobs using comprehensive pipeline log analysis"""
        patterns = []
        
        log.debug(f"Extracting error patterns from {len(failed_jobs)} failed jobs")
        
        for job in failed_jobs:
            # Basic pattern extraction
            if job.get('failure_reason'):
                patterns.append(job['failure_reason'])
                log.debug(f"Added failure reason pattern: {job['failure_reason']}")
            
            # Job name and stage context for pattern recognition
            job_name = job.get('name', '').lower()
            stage = job.get('stage', '').lower()
            
            # Enhanced pattern detection based on job context
            if 'test' in job_name:
                patterns.append('test_failure')
                log.debug(f"Detected test failure pattern from job: {job_name}")
            elif 'build' in job_name or 'compile' in job_name:
                patterns.append('build_failure')
                log.debug(f"Detected build failure pattern from job: {job_name}")
            elif any(keyword in job_name for keyword in ['lint', 'quality', 'sonar', 'code-quality']):
                patterns.append('quality_failure')
                log.debug(f"Detected quality failure pattern from job: {job_name}")
            elif 'sonar' in job_name or 'sonar' in stage:
                patterns.append('sonar_quality_gate_failure')
                log.debug(f"Detected sonar quality gate failure from job: {job_name}")
            elif 'deploy' in job_name:
                patterns.append('deployment_failure')
                log.debug(f"Detected deployment failure pattern from job: {job_name}")
            elif 'security' in job_name:
                patterns.append('security_failure')
                log.debug(f"Detected security failure pattern from job: {job_name}")
            
            # Check stage for additional context
            if 'quality' in stage or 'sonar' in stage:
                patterns.append('quality_gate_failure')
                log.debug(f"Detected quality gate failure from stage: {stage}")
            elif 'test' in stage:
                patterns.append('test_stage_failure')
                log.debug(f"Detected test stage failure from stage: {stage}")
        
        unique_patterns = list(set(patterns))  # Remove duplicates
        log.debug(f"Extracted {len(unique_patterns)} unique error patterns: {unique_patterns}")
        return unique_patterns
    
    async def _analyze_pipeline_logs_for_context(self, failed_jobs: List[Dict], error_patterns: List[str], session: Dict) -> Dict[str, Any]:
        """Analyze pipeline logs to extract detailed failure context"""
        try:
            # Extract pipeline and project information from session
            session_id = session.get('session_id') or session.get('id', 'unknown')
            project_id = session.get('project_id') or session.get('gitlab_project_id')
            pipeline_id = session.get('pipeline_id')
            
            if not pipeline_id or not project_id:
                log.warning(f"Missing pipeline or project ID for session {session_id}")
                return {"logs_analyzed": False, "failure_indicators": []}
            
            log.debug(f"Analyzing pipeline logs for session {session_id}, pipeline {pipeline_id}")
            
            log_patterns = []
            
            for job in failed_jobs:
                job_name = job.get('name', '').lower()
                stage = job.get('stage', '').lower()
                failure_reason = job.get('failure_reason', '').lower()
                
                # Enhanced pattern detection for supervisor agent routing
                if any(keyword in job_name for keyword in ['sonar', 'quality', 'lint', 'security', 'coverage']):
                    log_patterns.append({
                        "type": "quality_failure",
                        "job": job_name,
                        "stage": stage,
                        "context": f"Quality-related job failed: {job_name}",
                        "suggested_agent": "quality"
                    })
                elif any(keyword in stage for keyword in ['quality', 'sonar', 'test']):
                    log_patterns.append({
                        "type": "quality_stage_failure",
                        "job": job_name,
                        "stage": stage,
                        "context": f"Quality stage failure in {stage}",
                        "suggested_agent": "quality"
                    })
                else:
                    # All other failures (build, deploy, infrastructure, etc.) go to pipeline agent
                    failure_type = "build_failure" if 'build' in job_name else "pipeline_failure"
                    log_patterns.append({
                        "type": failure_type,
                        "job": job_name,
                        "stage": stage,
                        "context": f"Pipeline/build failure in {job_name} (stage: {stage})",
                        "suggested_agent": "pipeline"
                    })
            
            return {
                "logs_analyzed": True,
                "pipeline_id": pipeline_id,
                "project_id": project_id,
                "failure_indicators": log_patterns,
                "analysis_timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            log.error(f"Error analyzing pipeline logs for session {session.get('session_id', 'unknown')}: {e}", exc_info=True)
            return {"logs_analyzed": False, "error": str(e), "failure_indicators": []}
    
    def _find_recurring_patterns(self, fix_attempts: List[Dict]) -> List[str]:
        """Find patterns that appear in multiple attempts"""
        all_patterns = []
        
        for attempt in fix_attempts:
            all_patterns.extend(attempt.get('error_patterns', []))
        
        # Find patterns that appear more than once
        pattern_counts = {}
        for pattern in all_patterns:
            pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
        
        recurring = [p for p, count in pattern_counts.items() if count > 1]
        return recurring
    
    def _suggest_new_approach(self, fix_attempts: List[Dict], current_errors: List[str]) -> str:
        """Suggest a new approach based on failure patterns"""
        
        if not fix_attempts:
            return "Initial fix attempt - analyze root cause carefully"
        
        recurring = self._find_recurring_patterns(fix_attempts)
        
        if recurring:
            if 'test_failure' in recurring:
                return "Tests are consistently failing - review test logic and dependencies"
            elif 'build_failure' in recurring:
                return "Build issues persist - check dependencies and compilation settings"
            elif 'quality_failure' in recurring:
                return "Quality checks failing - focus on code standards and linting rules"
            else:
                return f"Recurring issues with: {', '.join(recurring)} - try a different approach"
        
        # If errors are changing each time
        if len(fix_attempts) > 1:
            prev_errors = fix_attempts[-2].get('error_patterns', [])
            if set(current_errors) != set(prev_errors):
                return "Errors are changing - previous fix had partial success, refine the approach"
        
        return "Consider a more comprehensive fix addressing multiple issues"
    
    async def _determine_failure_agent_type(self, session: Dict, failure_analysis: Dict) -> str:
        """Use supervisor agent to intelligently determine which agent should handle the retry"""
        try:
            # Get session ID safely
            session_id = session.get('session_id') or session.get('id', 'unknown')
            project_id = session.get('project_id') or session.get('gitlab_project_id', 'unknown')
            
            log.debug(f"Using supervisor agent to determine agent type for session {session_id}")
            
            # Import supervisor agent
            from agents.supervisor_agent import supervisor_agent
            
            # Create failure context for supervisor analysis
            failure_context = {
                "event_type": "fix_retry_analysis",
                "current_errors": failure_analysis.get('current_errors', []),
                "previous_attempts": failure_analysis.get('previous_attempts', []),
                "pipeline_analysis": failure_analysis.get('pipeline_analysis', {}),
                "recurring_patterns": failure_analysis.get('recurring_patterns', []),
                "session_metadata": {
                    "session_id": session_id,
                    "total_attempts": len(failure_analysis.get('previous_attempts', [])),
                    "fix_iteration": True
                }
            }
            
            # Use supervisor's fallback rule-based delegation to determine agent type
            # This leverages the supervisor's intelligent classification without full model invocation
            pipeline_info = session.get('webhook_data', {}).get('object_attributes', {})
            pipeline_stage = pipeline_info.get('stage', '').lower()
            
            # Use supervisor's rule-based classification logic
            is_quality_failure = False
            
            # Check for quality indicators in current errors and patterns
            current_errors = failure_analysis.get('current_errors', [])
            error_text = ' '.join([str(error).lower() for error in current_errors])
            
            quality_keywords = ['quality', 'sonar', 'code-quality', 'lint', 'security', 'vulnerability', 
                              'coverage', 'maintainability', 'reliability', 'code_smell']
            
            # Quality detection logic
            quality_in_errors = any(keyword in error_text for keyword in quality_keywords)
            quality_in_stage = any(keyword in pipeline_stage for keyword in ["quality", "sonar", "test", "coverage"])
            
            if quality_in_errors or quality_in_stage:
                is_quality_failure = True
                log.debug(f"Supervisor classification: Quality failure detected")
                agent_type = "quality"
            else:
                log.debug(f"Supervisor classification: Pipeline failure detected (including infrastructure issues)")
                agent_type = "pipeline"  # Pipeline agent handles all non-quality issues, including infrastructure
            
            log.info(f"Supervisor determined agent type '{agent_type}' for session {session_id}")
            return agent_type
            
        except Exception as e:
            log.error(f"Error using supervisor for agent determination: {e}", exc_info=True)
            # Safe fallback to pipeline agent
            return "pipeline"
    def _extract_successful_patterns(self, session: Dict) -> Dict:
        """Extract patterns from a successful fix"""
        return {
            "original_error": session.get('webhook_data', {}).get('failure_summary'),
            "fix_attempts": len(session.get('fix_attempts', [])),
            "final_approach": session.get('last_failure_analysis', {}).get('suggested_approach'),
            "session_type": session.get('session_type')
        }
    
    async def _store_successful_pattern(self, success_record: Dict):
        """Store successful pattern for future learning"""
        # This could integrate with your vector store
        # For now, just log it
        log.info(f"Storing successful pattern: {success_record['session_id']}")
        # Future: await vector_store.store_success(success_record)