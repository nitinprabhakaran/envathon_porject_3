"""
Fix Iteration Handler
Manages automatic iteration and reapplication of fixes when pipelines fail
"""
from typing import Dict, Any, Optional
from datetime import datetime
from utils.logger import log
from db.session_manager import SessionManager
from config import settings

# Import local branch naming utilities
from utils.branch_naming import (
    safe_extract_session_id, 
    is_fix_branch, 
    extract_branch_info
)


class FixIterationHandler:
    """Handles fix iteration logic and automatic reapplication"""
    
    def __init__(self):
        self.session_manager = SessionManager()
    
    async def handle_fix_branch_success(
        self, 
        session_id: str, 
        branch_name: str, 
        pipeline_id: str,
        webhook_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle successful fix branch pipeline"""
        try:
            # Get the current fix attempt
            fix_attempts = await self.session_manager.get_fix_attempts(session_id)
            current_attempt = None
            
            for attempt in fix_attempts:
                if attempt.get("branch_name") == branch_name and attempt.get("status") == "pending":
                    current_attempt = attempt
                    break
            
            if not current_attempt:
                log.warning(f"No pending fix attempt found for branch {branch_name}")
                return {"status": "error", "reason": "No pending fix attempt found"}
            
            # Mark the fix attempt as successful
            await self.session_manager.update_fix_attempt(
                session_id,
                current_attempt["attempt_number"],
                "success",
                mr_id=current_attempt.get("merge_request_id"),
                mr_url=current_attempt.get("merge_request_url")
            )
            
            # Add comprehensive success message to conversation
            pipeline_url = webhook_data.get("object_attributes", {}).get("web_url")
            session = await self.session_manager.get_session(session_id)
            session_type = session.get("session_type", "pipeline")
            
            # Get all fix attempts to show progress
            all_attempts = await self.session_manager.get_fix_attempts(session_id)
            successful_attempts = [att for att in all_attempts if att.get("status") == "success"]
            
            success_message = f"✅ **Fix Successful!**\n\n"
            success_message += f"The {session_type} fix on branch `{branch_name}` has passed all checks.\n\n"
            
            if len(successful_attempts) > 1:
                success_message += f"**Fix Iteration History:** {len(successful_attempts)}/{len(all_attempts)} attempts successful\n\n"
            
            success_message += f"**Merge Request:** {current_attempt.get('merge_request_url', 'N/A')}\n\n"
            success_message += f"**Next Steps:**\n"
            success_message += f"1. 🔍 **Review Changes:** Check the code changes in the merge request\n"
            success_message += f"2. ✅ **Approve & Merge:** Merge when ready to apply the fix\n"
            success_message += f"3. 🚀 **Deployment:** The fix will be applied to the target branch after merge\n"
            success_message += f"4. 📊 **Monitor:** Watch for improved {session_type} metrics\n\n"
            
            if pipeline_url:
                success_message += f"[View Successful Pipeline]({pipeline_url})\n\n"
            
            success_message += f"🎉 **Great job!** The AI successfully identified and fixed the issue."
            
            await self.session_manager.add_message(
                session_id,
                "assistant",
                success_message
            )
            
            # Update webhook data for UI
            await self._update_webhook_data_with_success(session_id, current_attempt["attempt_number"])
            
            log.info(f"Marked fix attempt #{current_attempt['attempt_number']} as successful for session {session_id}")
            
            return {
                "status": "success",
                "attempt_number": current_attempt["attempt_number"],
                "message": "Fix attempt marked as successful"
            }
            
        except Exception as e:
            log.error(f"Error handling fix branch success: {e}", exc_info=True)
            return {"status": "error", "reason": str(e)}
    
    async def handle_fix_branch_failure(
        self, 
        session_id: str, 
        branch_name: str, 
        pipeline_id: str,
        webhook_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle failed fix branch pipeline and trigger new iteration"""
        try:
            # Get the current fix attempt
            fix_attempts = await self.session_manager.get_fix_attempts(session_id)
            current_attempt = None
            
            for attempt in fix_attempts:
                if attempt.get("branch_name") == branch_name and attempt.get("status") == "pending":
                    current_attempt = attempt
                    break
            
            if not current_attempt:
                log.warning(f"No pending fix attempt found for branch {branch_name}")
                return {"status": "error", "reason": "No pending fix attempt found"}
            
            # Mark current attempt as failed
            error_summary = self._extract_error_summary(webhook_data)
            await self.session_manager.update_fix_attempt(
                session_id,
                current_attempt["attempt_number"],
                "failed",
                error_details=error_summary
            )
            
            # Check if we can create another iteration
            iteration_count = len(fix_attempts)
            max_iterations = getattr(settings, 'max_fix_attempts', 5)
            
            if iteration_count >= max_iterations:
                # Maximum iterations reached - comprehensive failure message
                session = await self.session_manager.get_session(session_id)
                session_type = session.get("session_type", "pipeline")
                
                failure_message = f"❌ **Maximum Fix Attempts Reached**\n\n"
                failure_message += f"The {session_type} fix has failed after {iteration_count} attempts. "
                failure_message += f"This indicates a complex issue that requires manual investigation.\n\n"
                
                failure_message += f"**Latest Error:** {error_summary}\n\n"
                
                failure_message += f"**🔍 Recommended Actions:**\n"
                failure_message += f"1. **Review Analysis:** Check all {iteration_count} fix attempts below\n"
                failure_message += f"2. **Manual Investigation:** The issue may involve:\n"
                failure_message += f"   - Complex interdependent problems\n"
                failure_message += f"   - Environmental or infrastructure issues\n"
                failure_message += f"   - Dependencies not visible in logs/code\n"
                failure_message += f"3. **Break Down Problem:** Consider smaller, incremental changes\n"
                failure_message += f"4. **Expert Review:** Get human developer input\n"
                failure_message += f"5. **System Check:** Verify CI/CD environment and tools\n\n"
                
                failure_message += f"**📋 Complete Fix History:**\n"
                for i, att in enumerate(fix_attempts):
                    status_icon = "✅" if att['status'] == 'success' else "❌" if att['status'] == 'failed' else "⏳"
                    mr_info = f" - [MR #{att.get('merge_request_id', 'N/A')}]({att.get('merge_request_url', '#')})" if att.get('merge_request_url') else ""
                    failure_message += f"- **Attempt #{att['attempt_number']}:** {status_icon} `{att['branch_name']}` - {att['status']}{mr_info}\n"
                
                failure_message += f"\n💡 **Tip:** You can still manually review and merge any successful partial fixes from the attempts above."
                
                await self.session_manager.add_message(
                    session_id,
                    "assistant",
                    failure_message
                )
                
                await self._update_webhook_data_with_failure(session_id, current_attempt["attempt_number"], error_summary)
                
                return {
                    "status": "max_attempts_reached",
                    "attempt_number": current_attempt["attempt_number"],
                    "message": f"Maximum attempts ({max_iterations}) reached"
                }
            
            # Create iteration message for user visibility
            user_message = f"🔄 **Starting Fix Iteration #{iteration_count + 1}**\n\n"
            user_message += f"The previous fix attempt failed. I'm now analyzing the failure and creating an improved fix.\n\n"
            user_message += f"**Previous Error:** {error_summary}\n\n"
            user_message += f"**Current Status:** Iteration {iteration_count + 1} of {max_iterations}\n\n"
            user_message += f"I'll analyze the latest logs and create a targeted fix that addresses both the original issue and this new failure..."
            
            await self.session_manager.add_message(
                session_id,
                "assistant",
                user_message
            )
            
            # Update webhook data to show failure
            await self._update_webhook_data_with_failure(session_id, current_attempt["attempt_number"], error_summary)
            
            # Trigger automatic reanalysis and fix creation
            await self._trigger_fix_iteration(session_id, iteration_count + 1, error_summary)
            
            log.info(f"Successfully triggered fix iteration #{iteration_count + 1} for session {session_id}")
            
            return {
                "status": "iteration_triggered",
                "attempt_number": iteration_count + 1,
                "message": f"Fix iteration #{iteration_count + 1} triggered automatically"
            }
            
        except Exception as e:
            log.error(f"Error handling fix branch failure: {e}", exc_info=True)
            return {"status": "error", "reason": str(e)}
    
    async def _trigger_fix_iteration(
        self, 
        session_id: str, 
        iteration_number: int, 
        previous_error: str
    ):
        """Trigger automatic fix iteration by invoking the agent"""
        try:
            # Get session data
            session = await self.session_manager.get_session(session_id)
            if not session:
                log.error(f"Session {session_id} not found for fix iteration")
                return
            
            session_type = session.get("session_type", "pipeline")
            
            # Import the appropriate agent
            if session_type == "pipeline":
                from agents.pipeline_agent import PipelineAgent
                agent = PipelineAgent()
            elif session_type == "quality":
                from agents.quality_agent import QualityAgent
                agent = QualityAgent()
            else:
                log.error(f"Unknown session type: {session_type}")
                return
            
            # Create optimized iteration message based on session type and iteration number
            iteration_prompt = self._create_iteration_prompt(
                session_type, iteration_number, previous_error, session
            )
            
            # Get conversation history for context
            conversation_history = session.get("conversation_history", [])
            
            # Invoke the agent to create the next iteration
            project_id = session.get("project_id", "")
            
            log.info(f"Triggering automatic fix iteration #{iteration_number} for session {session_id}")
            log.info(f"Using {session_type} agent for iteration")
            
            # Call the appropriate method based on agent type (different signatures)
            if session_type == "quality":
                # Quality agent expects context parameter
                context = {"project_id": project_id}
                response = await agent.handle_user_message(
                    session_id=session_id,
                    message=iteration_prompt,
                    conversation_history=conversation_history,
                    context=context
                )
            else:
                # Pipeline agent expects project_id parameter
                response = await agent.handle_user_message(
                    session_id=session_id,
                    message=iteration_prompt,
                    project_id=project_id,
                    conversation_history=conversation_history
                )
            
            log.info(f"Automatic fix iteration #{iteration_number} completed for session {session_id}")
            log.info(f"Agent response length: {len(response) if response else 0}")
            
            # Check if the response contains an MR URL, indicating successful fix creation
            if response and ("merge_request" in response.lower() or "mr" in response.lower()):
                log.info(f"Fix iteration #{iteration_number} appears to have created a merge request")
            else:
                log.warning(f"Fix iteration #{iteration_number} may not have created a merge request")
            
            return response
            
        except Exception as e:
            log.error(f"Error triggering fix iteration: {e}", exc_info=True)
            # Add error message to conversation
            await self.session_manager.add_message(
                session_id,
                "assistant",
                f"❌ **Automatic Fix Iteration Failed**\n\n"
                f"Unable to automatically create fix iteration #{iteration_number}.\n"
                f"Error: {str(e)}\n\n"
                f"Please manually analyze the failure and create the next fix."
            )
    
    async def _update_webhook_data_with_success(self, session_id: str, attempt_number: int):
        """Update webhook data to reflect successful fix attempt"""
        try:
            session = await self.session_manager.get_session(session_id)
            if not session:
                return
            
            webhook_data = session.get("webhook_data", {})
            fix_attempts_data = webhook_data.get("fix_attempts", [])
            
            # Update the specific attempt
            for attempt in fix_attempts_data:
                if attempt.get("attempt_number") == attempt_number:
                    attempt["status"] = "success"
                    attempt["succeeded_at"] = datetime.utcnow().isoformat()
                    break
            
            webhook_data["fix_attempts"] = fix_attempts_data
            await self.session_manager.update_session_metadata(session_id, {"webhook_data": webhook_data})
            
        except Exception as e:
            log.error(f"Error updating webhook data with success: {e}")
    
    async def _update_webhook_data_with_failure(self, session_id: str, attempt_number: int, error_summary: str):
        """Update webhook data to reflect failed fix attempt"""
        try:
            session = await self.session_manager.get_session(session_id)
            if not session:
                return
            
            webhook_data = session.get("webhook_data", {})
            fix_attempts_data = webhook_data.get("fix_attempts", [])
            
            # Update the specific attempt
            for attempt in fix_attempts_data:
                if attempt.get("attempt_number") == attempt_number:
                    attempt["status"] = "failed"
                    attempt["failed_at"] = datetime.utcnow().isoformat()
                    attempt["error_summary"] = error_summary
                    break
            
            webhook_data["fix_attempts"] = fix_attempts_data
            await self.session_manager.update_session_metadata(session_id, {"webhook_data": webhook_data})
            
        except Exception as e:
            log.error(f"Error updating webhook data with failure: {e}")
    
    def _create_iteration_prompt(
        self, 
        session_type: str, 
        iteration_number: int, 
        previous_error: str,
        session: Dict[str, Any]
    ) -> str:
        """Create iteration prompts using the exact working patterns from iteration_fixed_v1"""
        
        # Get fix attempts for context
        branch_name = session.get("current_fix_branch", "unknown")
        
        if session_type == "quality":
            # Use the exact working quality analysis prompt pattern
            return f"""## 🔍 Quality Gate Analysis - Fix Iteration #{iteration_number}

A SonarQube quality gate fix has failed and requires comprehensive re-analysis. To get started:

1. **First, get the failure context** using the `get_failure_context` tool to understand:
   - Project details and SonarQube configuration
   - Quality gate status and failed conditions
   - Pipeline information from the failed fix attempt
   - Specific metrics that are still failing

2. **Then proceed with detailed analysis**:
   - Retrieve detailed issues from SonarQube using the project key
   - Examine the most critical bugs, vulnerabilities, and code smells
   - Analyze affected files and understand the quality problems
   - Prioritize fixes based on severity and impact
   - Provide comprehensive solutions to improve code quality

**Previous Fix Attempt Analysis:**
- Branch: `{branch_name}`
- Error: {previous_error}
- Iteration: #{iteration_number} of 5

**Analysis Instructions:**
- Focus on addressing the failed quality gate conditions first
- Build upon any successful changes from previous attempts
- Use the available tools to get current project metrics from SonarQube
- If you can access the files, retrieve the problematic code files
- Provide specific fixes for the quality issues found
- Focus on the most critical issues first: security vulnerabilities, bugs, and critical code smells

Start by calling `get_failure_context()` to get all the essential information you need for the analysis."""
            
        else:
            # Use the exact working pipeline analysis prompt pattern
            return f"""## 🔍 Pipeline Failure Analysis - Fix Iteration #{iteration_number}

A GitLab CI/CD pipeline fix has failed and requires comprehensive re-analysis. To get started:

1. **First, get the failure context** using the `get_failure_context` tool to understand:
   - Project details and repository information
   - Pipeline information (ID, branch, commit details)
   - Failed job details with IDs for log retrieval
   - Overall pipeline status and timing

2. **Then proceed with detailed analysis**:
   - Retrieve logs for the failed job(s) using the provided Job IDs
   - Examine relevant files in the project repository
   - Analyze the failure patterns based on job names and stages
   - Provide specific solutions targeting the identified failure types

**Previous Fix Attempt Analysis:**
- Branch: `{branch_name}`
- Error: {previous_error}
- Iteration: #{iteration_number} of 5

**Analysis Instructions:**
- Build upon any successful changes from previous attempts
- Focus on making the pipeline pass while maintaining existing fixes
- Use the available tools to gather information and implement solutions
- Create proper merge requests with tested solutions
- Handle failed fix attempts by analyzing what went wrong

Start by calling `get_failure_context()` to get all the essential information you need for the analysis."""

    def _extract_error_summary(self, webhook_data: Dict[str, Any]) -> str:
        """Extract a comprehensive summary of the error from webhook data"""
        try:
            error_parts = []
            
            # Extract error information from GitLab webhook
            builds = webhook_data.get("builds", [])
            if builds:
                failed_builds = [b for b in builds if b.get("status") == "failed"]
                if not failed_builds:
                    failed_builds = builds  # If no failed builds, take all builds
                
                for build in failed_builds[:2]:  # Limit to first 2 failed builds
                    job_name = build.get('name', 'unknown')
                    stage = build.get('stage', 'unknown')
                    failure_reason = build.get('failure_reason', '')
                    
                    error_part = f"Job '{job_name}' in stage '{stage}'"
                    if failure_reason:
                        error_part += f" - {failure_reason}"
                    error_parts.append(error_part)
            
            # If no build info, try pipeline-level info
            if not error_parts:
                pipeline = webhook_data.get("object_attributes", {})
                status = pipeline.get('status', 'unknown')
                error_parts.append(f"Pipeline failed with status: {status}")
            
            # Combine all error information
            if len(error_parts) == 1:
                return error_parts[0]
            elif len(error_parts) > 1:
                return f"Multiple failures: {'; '.join(error_parts)}"
            else:
                return "Pipeline failed (no specific error details available)"
                
        except Exception as e:
            log.error(f"Error extracting failure details: {e}")
            return f"Pipeline failed (error extracting details: {str(e)})"
    
    async def get_fix_attempt_status(self, session_id: str) -> Dict[str, Any]:
        """Get the current status of fix attempts for a session"""
        try:
            fix_attempts = await self.session_manager.get_fix_attempts(session_id)
            
            if not fix_attempts:
                return {"status": "no_attempts", "attempts": []}
            
            successful_attempts = [att for att in fix_attempts if att.get("status") == "success"]
            failed_attempts = [att for att in fix_attempts if att.get("status") == "failed"]
            pending_attempts = [att for att in fix_attempts if att.get("status") == "pending"]
            
            return {
                "status": "active",
                "total_attempts": len(fix_attempts),
                "successful": len(successful_attempts),
                "failed": len(failed_attempts),
                "pending": len(pending_attempts),
                "attempts": fix_attempts,
                "latest_attempt": fix_attempts[-1] if fix_attempts else None
            }
            
        except Exception as e:
            log.error(f"Error getting fix attempt status: {e}")
            return {"status": "error", "error": str(e)}
