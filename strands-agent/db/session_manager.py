"""Session management for persistent conversations"""
import asyncpg
import json
import hashlib
import uuid
from typing import Dict, Any, Optional, List, Union
from uuid import UUID
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from utils.logger import log
from config import settings
from db.models import SessionContext

class SessionManager:
    def __init__(self):
        self._pool = None
    
    async def init_pool(self):
        """Initialize connection pool"""
        if not self._pool:
            # For local development, use minimal pooling
            if hasattr(settings, 'environment') and settings.environment == 'local':
                self._pool = await asyncpg.create_pool(
                    settings.database_url, 
                    min_size=1, 
                    max_size=2
                )
                log.info("Database connection pool initialized for local development (min: 1, max: 2)")
            else:
                # Production-style pooling for other environments
                self._pool = await asyncpg.create_pool(
                    settings.database_url, 
                    min_size=settings.db_pool_min_size, 
                    max_size=settings.db_pool_max_size
                )
                log.info(f"Database connection pool initialized (min: {settings.db_pool_min_size}, max: {settings.db_pool_max_size})")
    
    @asynccontextmanager
    async def get_connection(self):
        """Get database connection from pool"""
        await self.init_pool()
        async with self._pool.acquire() as conn:
            yield conn
    
    # Update create_session method to include parent_session_id:
    async def create_session(
        self,
        session_id: str,
        session_type: str,
        project_id: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create new session"""
        expires_at = datetime.utcnow() + timedelta(minutes=settings.session_timeout_minutes)
        
        async with self.get_connection() as conn:
            session = await conn.fetchrow(
                """
                INSERT INTO sessions (
                    id, session_type, project_id, status,
                    project_name, branch, pipeline_id, 
                    pipeline_url, job_name, failed_stage,
                    quality_gate_status, webhook_data, expires_at,
                    current_fix_branch, parent_session_id
                ) VALUES ($1, $2, $3, 'active', $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                RETURNING *
                """,
                session_id, session_type, project_id,
                metadata.get("project_name"),
                metadata.get("branch"),
                metadata.get("pipeline_id"),
                metadata.get("pipeline_url"),
                metadata.get("job_name"),
                metadata.get("failed_stage"),
                metadata.get("quality_gate_status"),
                json.dumps(metadata.get("webhook_data", {})),
                expires_at,
                metadata.get("current_fix_branch"),
                metadata.get("parent_session_id")
            )
            log.info(f"Created {session_type} session {session_id} with {settings.session_timeout_minutes} minute timeout")
            return dict(session)
    
    async def get_session(self, session_id: Union[str, UUID]) -> Optional[Dict[str, Any]]:
        """Get session by ID"""
        async with self.get_connection() as conn:
            # Ensure session_id is a string for database query
            if isinstance(session_id, UUID):
                session_id_str = str(session_id)
            else:
                session_id_str = session_id
                
            session = await conn.fetchrow(
                "SELECT * FROM sessions WHERE id = $1",
                session_id_str
            )
            if session:
                result = dict(session)
                # Parse JSON fields
                for field in ['conversation_history', 'webhook_data', 'fixes_applied']:
                    if field in result and isinstance(result[field], str):
                        try:
                            result[field] = json.loads(result[field])
                        except:
                            result[field] = [] if field in ['conversation_history', 'fixes_applied'] else {}
                return result
            return None
    
    async def get_session_context(self, session_id: str) -> Optional[SessionContext]:
        """Get complete session context for agent"""
        session = await self.get_session(session_id)
        if not session:
            return None
        
        return SessionContext(
            session_id=str(session_id),  # Ensure it's a string
            session_type=session['session_type'],
            project_id=str(session['project_id']),  # Ensure it's a string
            project_name=session.get('project_name'),
            pipeline_id=session.get('pipeline_id'),
            pipeline_url=session.get('pipeline_url'),
            branch=session.get('branch'),
            commit_sha=session.get('commit_sha'),
            failed_stage=session.get('failed_stage'),
            job_name=session.get('job_name'),
            sonarqube_key=session.get('webhook_data', {}).get('project', {}).get('key'),
            quality_gate_status=session.get('quality_gate_status'),
            gitlab_project_id=str(session.get('project_id')),  # Ensure it's a string
            created_at=session.get('created_at'),
            webhook_data=session.get('webhook_data', {})
        )
    
    async def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Get all active sessions"""
        async with self.get_connection() as conn:
            sessions = await conn.fetch(
                """
                SELECT * FROM sessions 
                WHERE status = 'active' 
                AND expires_at > CURRENT_TIMESTAMP
                ORDER BY created_at DESC
                """
            )
            results = []
            for session in sessions:
                result = dict(session)
                # Parse JSON fields
                for field in ['conversation_history', 'webhook_data', 'fixes_applied']:
                    if field in result and isinstance(result[field], str):
                        try:
                            result[field] = json.loads(result[field])
                        except:
                            result[field] = [] if field in ['conversation_history', 'fixes_applied'] else {}
                
                # Map database column names to API names for consistency
                if 'mr_url' in result:
                    result['merge_request_url'] = result['mr_url']
                if 'mr_id' in result:
                    result['merge_request_id'] = result['mr_id']
                    
                results.append(result)
            log.debug(f"Found {len(results)} active sessions")
            return results
    
    async def add_message(self, session_id: str, role: str, content: str):
        """Add message to conversation history"""
        async with self.get_connection() as conn:
            # Ensure session_id is a string for database query
            if isinstance(session_id, UUID):
                session_id_str = str(session_id)
            else:
                session_id_str = session_id
                
            # Get current history
            current = await conn.fetchval(
                "SELECT conversation_history FROM sessions WHERE id = $1",
                session_id_str
            )
            
            history = json.loads(current) if current else []
            history.append({
                "role": role,
                "content": content,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # Update
            await conn.execute(
                """
                UPDATE sessions 
                SET conversation_history = $2::jsonb,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                session_id_str, json.dumps(history)
            )
            log.debug(f"Added {role} message to session {session_id}")
    
    async def store_tracked_file(self, session_id: str, file_path: str, content: Optional[str], status: str = "success"):
        """Store a tracked file in the database"""
        async with self.get_connection() as conn:
            # Ensure session_id is a string for database query
            if isinstance(session_id, UUID):
                session_id_str = str(session_id)
            else:
                session_id_str = session_id
                
            await conn.execute(
                """
                INSERT INTO tracked_files (session_id, file_path, tracked_content, status, metadata)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (session_id, file_path) 
                DO UPDATE SET 
                    tracked_content = $3,
                    status = $4,
                    last_modified = CURRENT_TIMESTAMP,
                    metadata = $5
                """,
                session_id_str, file_path, content, status, json.dumps({})
            )
            log.info(f"Stored tracked file {file_path} (status: {status}) for session {session_id}")
    
    async def get_tracked_files(self, session_id: str) -> Dict[str, Any]:
        """Get all tracked files for a session"""
        async with self.get_connection() as conn:
            # Ensure session_id is a string for database query
            if isinstance(session_id, UUID):
                session_id_str = str(session_id)
            else:
                session_id_str = session_id
                
            files = await conn.fetch(
                """
                SELECT file_path, tracked_content, status, tracked_at, metadata
                FROM tracked_files
                WHERE session_id = $1
                ORDER BY tracked_at DESC
                """,
                session_id_str
            )
            
            result = {}
            for file in files:
                result[file['file_path']] = {
                    'tracked_content': file['tracked_content'],  # Fix key name
                    'status': file['status'],
                    'tracked_at': file['tracked_at'].isoformat() if file['tracked_at'] else None,
                    'metadata': json.loads(file['metadata']) if file['metadata'] else {}
                }
            return result
    
    async def create_fix_attempt(self, session_id: str, branch_name: str, files_changed: List[str]) -> int:
        """Create a new fix attempt record"""
        branch_name = branch_name.strip()
        async with self.get_connection() as conn:
            # Ensure session_id is a string for database query
            if isinstance(session_id, UUID):
                session_id_str = str(session_id)
            else:
                session_id_str = session_id
            
            # Use transaction for atomicity
            async with conn.transaction():
                # Lock the session row to prevent concurrent modifications
                await conn.execute(
                    "SELECT id FROM sessions WHERE id = $1 FOR UPDATE",
                    session_id_str
                )
                
                # Now get the current iteration count
                current_iteration = await conn.fetchval(
                    "SELECT COALESCE(MAX(attempt_number), 0) FROM fix_attempts WHERE session_id = $1",
                    session_id_str
                )
                
                new_attempt = current_iteration + 1
                
                # Check if we're at the limit
                if new_attempt > settings.max_fix_attempts:
                    log.warning(f"Cannot create fix attempt #{new_attempt} - exceeds limit of {settings.max_fix_attempts}")
                    raise Exception(f"Maximum fix attempts ({settings.max_fix_attempts}) exceeded")
                
                # Create fix attempt
                await conn.execute(
                    """
                    INSERT INTO fix_attempts (session_id, attempt_number, branch_name, files_changed, status)
                    VALUES ($1, $2, $3, $4, 'pending')
                    """,
                    session_id_str, new_attempt, branch_name, json.dumps(files_changed)
                )
                
                # Update session
                await conn.execute(
                    """
                    UPDATE sessions 
                    SET current_fix_branch = $2, fix_iteration = $3
                    WHERE id = $1
                    """,
                    session_id_str, branch_name, new_attempt
                )
            
            log.info(f"Created fix attempt #{new_attempt} for session {session_id}")
            return new_attempt

    async def update_fix_attempt(self, session_id: str, attempt_number: int, status: str, 
                                mr_id: Optional[str] = None, mr_url: Optional[str] = None,
                                error_details: Optional[str] = None):
        """Update fix attempt status"""
        async with self.get_connection() as conn:
            # Ensure session_id is a string for database query
            if isinstance(session_id, UUID):
                session_id_str = str(session_id)
            else:
                session_id_str = session_id
                
            # Ensure mr_id is a string if provided
            mr_id_str = str(mr_id) if mr_id is not None else None
                
            await conn.execute(
                """
                UPDATE fix_attempts
                SET status = $3::VARCHAR(50), 
                    merge_request_id = $4,
                    merge_request_url = $5,
                    error_message = $6,
                    completed_at = CASE WHEN $3 IN ('success', 'failed') THEN CURRENT_TIMESTAMP ELSE NULL END
                WHERE session_id = $1 AND attempt_number = $2
                """,
                session_id_str, attempt_number, status, mr_id_str, mr_url, error_details
            )
            
            # Update session MR info if successful
            if status == "success" and mr_url:
                await conn.execute(
                    """
                    UPDATE sessions 
                    SET merge_request_url = $2, merge_request_id = $3
                    WHERE id = $1
                    """,
                    session_id_str, mr_url, mr_id_str
                )
            
            log.info(f"Updated fix attempt #{attempt_number} for session {session_id}: status={status}")

    async def _update_webhook_data_fix_status(self, session_id: str, attempt_number: int, status: str, 
                                            mr_id: Optional[str] = None, mr_url: Optional[str] = None):
        """Update webhook_data with fix attempt status for UI consistency"""
        async with self.get_connection() as conn:
            # Get current webhook_data
            current = await conn.fetchval(
                "SELECT webhook_data FROM sessions WHERE id = $1",
                str(session_id)
            )
            webhook_data = json.loads(current) if current else {}
            
            # Initialize fix_attempts if not exists
            if 'fix_attempts' not in webhook_data:
                webhook_data['fix_attempts'] = []
            
            # Update the specific attempt
            fix_attempts = webhook_data['fix_attempts']
            updated = False
            for attempt in fix_attempts:
                if attempt.get('attempt_number') == attempt_number:
                    attempt['status'] = status
                    if mr_id:
                        attempt['mr_id'] = mr_id
                    if mr_url:
                        attempt['mr_url'] = mr_url
                    if status == 'success':
                        attempt['succeeded_at'] = datetime.utcnow().isoformat()
                    elif status == 'failed':
                        attempt['failed_at'] = datetime.utcnow().isoformat()
                    updated = True
                    break
            
            # If not found, create new entry
            if not updated:
                # Get branch name from fix_attempts table
                branch_name = await conn.fetchval(
                    "SELECT branch_name FROM fix_attempts WHERE session_id = $1 AND attempt_number = $2",
                    str(session_id), attempt_number
                )
                fix_attempts.append({
                    'attempt_number': attempt_number,
                    'branch': branch_name,
                    'status': status,
                    'mr_id': mr_id,
                    'mr_url': mr_url,
                    'created_at': datetime.utcnow().isoformat()
                })
            
            # Update webhook_data
            await conn.execute(
                "UPDATE sessions SET webhook_data = $2::jsonb WHERE id = $1",
                str(session_id), json.dumps(webhook_data)
            )
    
    async def get_fix_attempts(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all fix attempts for a session"""
        # Ensure session_id is string
        session_id = str(session_id)
        
        async with self.get_connection() as conn:
            attempts = await conn.fetch(
                """
                SELECT * FROM fix_attempts
                WHERE session_id = $1
                ORDER BY attempt_number ASC
                """,
                session_id
            )

            log.debug(f"Found {len(attempts)} fix attempts for session {session_id}")

            results = []
            for attempt in attempts:
                result = dict(attempt)
                if result.get('files_changed'):
                    result['files_changed'] = json.loads(result['files_changed'])
                results.append(result)
            return results
    
    async def check_iteration_limit(self, session_id: str, limit: int = None) -> bool:
        """Check if we've reached the iteration limit"""
        # Ensure session_id is string
        session_id = str(session_id)
        
        if limit is None:
            limit = settings.max_fix_attempts
        attempts = await self.get_fix_attempts(session_id)
        return len(attempts) >= limit
    
    async def update_session_metadata(self, session_id: str, metadata: Dict[str, Any]):
        """Update session metadata"""
        async with self.get_connection() as conn:
            # Ensure session_id is a string for database query
            if isinstance(session_id, UUID):
                session_id_str = str(session_id)
            else:
                session_id_str = session_id
                
            # Handle webhook_data specially to merge it
            if "webhook_data" in metadata:
                # Get current webhook_data
                current = await conn.fetchval(
                    "SELECT webhook_data FROM sessions WHERE id = $1",
                    session_id_str
                )
                current_data = json.loads(current) if current else {}
                
                # Merge new data
                new_webhook_data = metadata["webhook_data"]
                if isinstance(new_webhook_data, dict):
                    current_data.update(new_webhook_data)
                    metadata["webhook_data"] = json.dumps(current_data)
                else:
                    metadata["webhook_data"] = json.dumps(new_webhook_data)
            
            # Build update query
            updates = []
            params = [session_id_str]
            param_num = 2
            
            for key, value in metadata.items():
                if key == "webhook_data":
                    updates.append(f"webhook_data = ${param_num}::jsonb")
                    params.append(value)
                elif key == "merge_request_url":
                    updates.append(f"mr_url = ${param_num}")
                    params.append(value)
                elif key == "merge_request_id":
                    updates.append(f"mr_id = ${param_num}")
                    params.append(value)
                elif key == "fixes_applied":
                    updates.append(f"fixes_applied = ${param_num}::jsonb")
                    params.append(json.dumps(value) if isinstance(value, (dict, list)) else value)
                elif key == "session_type":
                    updates.append(f"session_type = ${param_num}")
                    params.append(value)
                elif key == "current_fix_branch":
                    updates.append(f"current_fix_branch = ${param_num}")
                    params.append(value)
                elif key == "fix_iteration":
                    updates.append(f"fix_iteration = ${param_num}")
                    params.append(value)
                param_num += 1
            
            if updates:
                query = f"""
                    UPDATE sessions 
                    SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP
                    WHERE id = $1
                """
                await conn.execute(query, *params)
                log.debug(f"Updated metadata for session {session_id}")
    
    async def update_quality_metrics(self, session_id: str, metrics: Dict[str, Any]):
        """Update quality metrics for a session"""
        log.info(f"=== UPDATE_QUALITY_METRICS CALLED ===")
        log.info(f"Session ID: {session_id}")
        log.info(f"Metrics received: {metrics}")
        
        async with self.get_connection() as conn:
            # Check if session exists first
            existing = await conn.fetchval("SELECT id FROM sessions WHERE id = $1", session_id)
            log.info(f"Session exists in DB: {existing is not None}")
            
            if not existing:
                log.error(f"Session {session_id} not found in database!")
                return
            
            # Log the actual values being passed to the query
            total_issues = metrics.get("total_issues", 0)
            bug_count = metrics.get("bug_count", 0)
            vulnerability_count = metrics.get("vulnerability_count", 0)
            code_smell_count = metrics.get("code_smell_count", 0)
            critical_issues = metrics.get("critical_issues", 0)
            major_issues = metrics.get("major_issues", 0)
            
            log.info(f"SQL params: total_issues={total_issues}, bug_count={bug_count}, vulnerability_count={vulnerability_count}")
            log.info(f"SQL params: code_smell_count={code_smell_count}, critical_issues={critical_issues}, major_issues={major_issues}")
            
            result = await conn.execute(
                """
                UPDATE sessions 
                SET total_issues = $2,
                    critical_issues = $3,
                    major_issues = $4,
                    bug_count = $5,
                    vulnerability_count = $6,
                    code_smell_count = $7,
                    coverage = $8,
                    duplicated_lines_density = $9,
                    reliability_rating = $10,
                    security_rating = $11,
                    maintainability_rating = $12,
                    webhook_data = webhook_data || $13::jsonb,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                session_id,
                total_issues,
                critical_issues,
                major_issues,
                bug_count,
                vulnerability_count,
                code_smell_count,
                metrics.get("coverage"),
                metrics.get("duplicated_lines_density"),
                metrics.get("reliability_rating", "E")[:1],
                metrics.get("security_rating", "E")[:1],
                metrics.get("maintainability_rating", "E")[:1],
                json.dumps({"quality_metrics": metrics})
            )
            
            log.info(f"UPDATE query executed, result: {result}")
            
            # Verify the update worked
            verify = await conn.fetchrow(
                "SELECT total_issues, bug_count, vulnerability_count, code_smell_count FROM sessions WHERE id = $1", 
                session_id
            )
            log.info(f"Verification query result: {dict(verify) if verify else 'No result'}")
            
            log.info(f"Updated quality metrics for session {session_id}")
    
    async def mark_session_resolved(self, session_id: str):
        """Mark session as resolved"""
        async with self.get_connection() as conn:
            await conn.execute(
                "UPDATE sessions SET status = 'resolved' WHERE id = $1",
                session_id
            )
            log.info(f"Marked session {session_id} as resolved")
    
    async def cleanup_expired_sessions(self):
        """Clean up expired sessions"""
        async with self.get_connection() as conn:
            result = await conn.execute(
                """
                UPDATE sessions 
                SET status = 'expired' 
                WHERE status = 'active' 
                AND expires_at < CURRENT_TIMESTAMP
                """
            )
            count = int(result.split()[-1])
            if count > 0:
                log.info(f"Marked {count} sessions as expired")
    
    async def get_similar_fixes(self, error_signature: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get similar historical fixes"""
        async with self.get_connection() as conn:
            signature_hash = hashlib.sha256(error_signature.encode()).hexdigest()
            
            fixes = await conn.fetch(
                """
                SELECT h.*, s.project_name, s.created_at as fix_date
                FROM historical_fixes h
                JOIN sessions s ON h.session_id = s.id
                WHERE h.error_signature_hash = $1
                AND h.success_confirmed = true
                ORDER BY h.applied_at DESC
                LIMIT $2
                """,
                signature_hash, limit
            )
            
            return [dict(fix) for fix in fixes]
    
    async def get_sessions_by_mr(self, project_id: str, mr_id: str) -> List[Dict[str, Any]]:
        """Get sessions associated with a specific MR"""
        async with self.get_connection() as conn:
            sessions = await conn.fetch(
                """
                SELECT * FROM sessions 
                WHERE project_id = $1 
                AND merge_request_id = $2
                AND status = 'active'
                """,
                project_id, mr_id
            )
            return [dict(session) for session in sessions]
    
    async def get_sessions_by_fix_branch(self, project_id: str, branch_name: str) -> List[Dict[str, Any]]:
        """Get sessions that have fix attempts on a specific branch"""
        async with self.get_connection() as conn:
            sessions = await conn.fetch(
                """
                SELECT DISTINCT s.* FROM sessions s
                JOIN fix_attempts fa ON s.id = fa.session_id
                WHERE s.project_id = $1 
                AND fa.branch_name = $2
                AND s.status = 'active'
                """,
                project_id, branch_name
            )
            
            results = []
            for session in sessions:
                result = dict(session)
                # Parse JSON fields
                for field in ['conversation_history', 'webhook_data', 'fixes_applied']:
                    if field in result and isinstance(result[field], str):
                        try:
                            result[field] = json.loads(result[field])
                        except:
                            result[field] = [] if field in ['conversation_history', 'fixes_applied'] else {}
                results.append(result)
            return results
    
    async def handle_pipeline_success_on_fix_branch(self, project_id: str, branch_name: str, pipeline_id: str = None):
        """Handle successful pipeline on a fix branch - mark fix attempts as successful"""
        log.info(f"Processing pipeline success on fix branch: {branch_name} in project {project_id}")
        
        # Get all sessions with fix attempts on this branch
        sessions = await self.get_sessions_by_fix_branch(project_id, branch_name)
        
        for session in sessions:
            session_id = session['id']
            log.info(f"Checking session {session_id} for fix attempts on branch {branch_name}")
            
            # Get fix attempts for this session on this branch
            fix_attempts = await self.get_fix_attempts(session_id)
            
            for attempt in fix_attempts:
                if (attempt.get('branch_name', '').strip() == branch_name.strip() and 
                    attempt.get('status') == 'pending'):
                    
                    log.info(f"Marking fix attempt #{attempt['attempt_number']} as successful for session {session_id}")
                    
                    # Update fix attempt status to success
                    await self.update_fix_attempt(
                        session_id,
                        attempt['attempt_number'],
                        'success',
                        attempt.get('merge_request_id'),
                        attempt.get('merge_request_url')
                    )
                    
                    # Add success message to conversation
                    await self.add_message(
                        session_id,
                        "assistant",
                        f"✅ **Fix Successful!**\n\n"
                        f"The fix on branch `{branch_name}` has been successfully merged and the pipeline is now passing.\n"
                        f"Fix attempt #{attempt['attempt_number']} completed successfully."
                    )
                    
                    # Check if this fix resolves the session
                    await self._check_session_resolution(session_id)
    
    async def _check_session_resolution(self, session_id: str):
        """Check if session should be resolved based on successful fixes"""
        session = await self.get_session(session_id)
        if not session or session.get('status') != 'active':
            return
        
        # Get all fix attempts
        fix_attempts = await self.get_fix_attempts(session_id)
        
        # Check if we have successful fixes
        successful_attempts = [att for att in fix_attempts if att.get('status') == 'success']
        
        if successful_attempts:
            # For now, mark as resolved if we have any successful fix
            # Could be enhanced to check if the main branch pipeline also passes
            await self.mark_session_resolved(session_id)
            
            await self.add_message(
                session_id,
                "assistant",
                f"🎉 **Session Resolved!**\n\n"
                f"The issue has been successfully fixed and verified. "
                f"Total fix attempts: {len(fix_attempts)}, Successful: {len(successful_attempts)}"
            )
            
            log.info(f"Marked session {session_id} as resolved due to successful fix")
    
    async def handle_pipeline_failure_on_fix_branch(self, project_id: str, branch_name: str, error_details: str = None):
        """Handle failed pipeline on a fix branch - mark fix attempts as failed"""
        log.info(f"Processing pipeline failure on fix branch: {branch_name} in project {project_id}")
        
        # Get all sessions with fix attempts on this branch
        sessions = await self.get_sessions_by_fix_branch(project_id, branch_name)
        
        for session in sessions:
            session_id = session['id']
            
            # Get fix attempts for this session on this branch
            fix_attempts = await self.get_fix_attempts(session_id)
            
            for attempt in fix_attempts:
                if (attempt.get('branch_name', '').strip() == branch_name.strip() and 
                    attempt.get('status') == 'pending'):
                    
                    log.info(f"Marking fix attempt #{attempt['attempt_number']} as failed for session {session_id}")
                    
                    # Update fix attempt status to failed
                    await self.update_fix_attempt(
                        session_id,
                        attempt['attempt_number'],
                        'failed',
                        attempt.get('merge_request_id'),
                        attempt.get('merge_request_url'),
                        error_details
                    )
                    
                    # Add failure message to conversation
                    await self.add_message(
                        session_id,
                        "assistant",
                        f"❌ **Fix Attempt Failed**\n\n"
                        f"The fix on branch `{branch_name}` failed in the pipeline.\n"
                        f"Fix attempt #{attempt['attempt_number']} failed.\n"
                        f"Error: {error_details if error_details else 'Pipeline failed'}\n\n"
                        f"You can analyze the latest logs and create another fix."
                    )