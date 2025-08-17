"""Fix iteration handler for managing failed fix attempts"""

import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
from utils.logger import log
from db.session_manager import SessionManager

class FixIterationHandler:
    """Handles failed fix attempts and generates improved solutions"""
    
    def __init__(self):
        self.session_manager = SessionManager()
        self.max_attempts = int(os.getenv('MAX_FIX_ATTEMPTS', '3'))
        
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
            
            # Create fix attempt record
            fix_attempt = {
                "attempt": current_attempt,
                "timestamp": datetime.utcnow().isoformat(),
                "pipeline_id": webhook_data.get('object_attributes', {}).get('id'),
                "branch": webhook_data.get('object_attributes', {}).get('ref'),
                "failed_jobs": failed_jobs,
                "error_patterns": error_patterns,
                "status": pipeline_status
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
        
        for build in webhook_data.get('builds', []):
            if build.get('status') == 'failed':
                failed_jobs.append({
                    'name': build.get('name'),
                    'stage': build.get('stage'),
                    'failure_reason': build.get('failure_reason'),
                    'id': build.get('id')
                })
        
        return failed_jobs
    
    def _extract_error_patterns(self, failed_jobs: List[Dict]) -> List[str]:
        """Extract error patterns from failed jobs"""
        patterns = []
        
        for job in failed_jobs:
            # Basic pattern extraction
            if job.get('failure_reason'):
                patterns.append(job['failure_reason'])
            
            # Job name often indicates the type of failure
            job_name = job.get('name', '').lower()
            if 'test' in job_name:
                patterns.append('test_failure')
            elif 'build' in job_name or 'compile' in job_name:
                patterns.append('build_failure')
            elif 'lint' in job_name or 'quality' in job_name:
                patterns.append('quality_failure')
            elif 'deploy' in job_name:
                patterns.append('deployment_failure')
        
        return list(set(patterns))  # Remove duplicates
    
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