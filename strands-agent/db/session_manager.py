"""Session management for persistent conversations"""
import asyncpg
import json
import hashlib
from typing import Dict, Any, Optional, List
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
            self._pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10)
            log.info("Database connection pool initialized")
    
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
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID"""
        async with self.get_connection() as conn:
            session = await conn.fetchrow(
                "SELECT * FROM sessions WHERE id = $1",
                session_id
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
            session_id=session_id,
            session_type=session['session_type'],
            project_id=session['project_id'],
            project_name=session.get('project_name'),
            pipeline_id=session.get('pipeline_id'),
            pipeline_url=session.get('pipeline_url'),
            branch=session.get('branch'),
            commit_sha=session.get('commit_sha'),
            failed_stage=session.get('failed_stage'),
            job_name=session.get('job_name'),
            sonarqube_key=session.get('webhook_data', {}).get('project', {}).get('key'),
            quality_gate_status=session.get('quality_gate_status'),
            gitlab_project_id=session.get('project_id'),
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
                results.append(result)
            log.debug(f"Found {len(results)} active sessions")
            return results
    
    async def add_message(self, session_id: str, role: str, content: str):
        """Add message to conversation history"""
        async with self.get_connection() as conn:
            # Get current history
            current = await conn.fetchval(
                "SELECT conversation_history FROM sessions WHERE id = $1",
                session_id
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
                    last_activity = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                session_id, json.dumps(history)
            )
            log.debug(f"Added {role} message to session {session_id}")
    
    async def store_tracked_file(self, session_id: str, file_path: str, content: Optional[str], status: str = "success"):
        """Store a tracked file in the database"""
        async with self.get_connection() as conn:
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
                session_id, file_path, content, status, json.dumps({})
            )
            log.info(f"Stored tracked file {file_path} (status: {status}) for session {session_id}")
    
    async def get_tracked_files(self, session_id: str) -> Dict[str, Any]:
        """Get all tracked files for a session"""
        async with self.get_connection() as conn:
            files = await conn.fetch(
                """
                SELECT file_path, tracked_content, status, tracked_at, metadata
                FROM tracked_files
                WHERE session_id = $1
                ORDER BY tracked_at DESC
                """,
                session_id
            )
            
            result = {}
            for file in files:
                result[file['file_path']] = {
                    'content': file['tracked_content'],
                    'status': file['status'],
                    'tracked_at': file['tracked_at'].isoformat() if file['tracked_at'] else None,
                    'metadata': json.loads(file['metadata']) if file['metadata'] else {}
                }
            return result
    
    async def create_fix_attempt(self, session_id: str, branch_name: str, files_changed: List[str]) -> int:
        """Create a new fix attempt record"""
        branch_name = branch_name.strip()
        async with self.get_connection() as conn:
            # Ensure session_id is properly formatted
            import uuid
            if isinstance(session_id, str):
                session_uuid = uuid.UUID(session_id)
            else:
                session_uuid = session_id
            
            # Use transaction for atomicity
            async with conn.transaction():
                # Lock the session row to prevent concurrent modifications
                await conn.execute(
                    "SELECT id FROM sessions WHERE id = $1 FOR UPDATE",
                    session_uuid
                )
                
                # Now get the current iteration count
                current_iteration = await conn.fetchval(
                    "SELECT COALESCE(MAX(attempt_number), 0) FROM fix_attempts WHERE session_id = $1",
                    session_uuid
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
                    session_uuid, new_attempt, branch_name, json.dumps(files_changed)
                )
                
                # Update session
                await conn.execute(
                    """
                    UPDATE sessions 
                    SET current_fix_branch = $2, fix_iteration = $3
                    WHERE id = $1
                    """,
                    session_uuid, branch_name, new_attempt
                )
            
            log.info(f"Created fix attempt #{new_attempt} for session {session_id}")
            return new_attempt

    async def update_fix_attempt(self, session_id: str, attempt_number: int, status: str, 
                                mr_id: Optional[str] = None, mr_url: Optional[str] = None,
                                error_details: Optional[str] = None):
        """Update fix attempt status"""
        async with self.get_connection() as conn:
            # Ensure session_id is properly formatted
            import uuid
            if isinstance(session_id, str):
                session_uuid = uuid.UUID(session_id)
            else:
                session_uuid = session_id
                
            await conn.execute(
                """
                UPDATE fix_attempts
                SET status = $3::VARCHAR(20), 
                    merge_request_id = $4,
                    merge_request_url = $5,
                    error_details = $6,
                    completed_at = CASE WHEN $3 IN ('success', 'failed') THEN CURRENT_TIMESTAMP ELSE NULL END
                WHERE session_id = $1 AND attempt_number = $2
                """,
                session_uuid, attempt_number, status, mr_id, mr_url, error_details
            )
            
            # Update session MR info if successful
            if status == "success" and mr_url:
                await conn.execute(
                    """
                    UPDATE sessions 
                    SET merge_request_url = $2, merge_request_id = $3
                    WHERE id = $1
                    """,
                    session_uuid, mr_url, mr_id
                )
    
    async def get_fix_attempts(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all fix attempts for a session"""
        async with self.get_connection() as conn:
            # Convert session_id to UUID if it's a string
            import uuid
            if isinstance(session_id, str):
                session_uuid = uuid.UUID(session_id)
            else:
                session_uuid = session_id

            attempts = await conn.fetch(
                """
                SELECT * FROM fix_attempts
                WHERE session_id = $1
                ORDER BY attempt_number ASC
                """,
                session_uuid
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
        if limit is None:
            limit = settings.max_fix_attempts
        attempts = await self.get_fix_attempts(session_id)
        return len(attempts) >= limit
    
    async def update_session_metadata(self, session_id: str, metadata: Dict[str, Any]):
        """Update session metadata"""
        async with self.get_connection() as conn:
            # Handle webhook_data specially to merge it
            if "webhook_data" in metadata:
                # Get current webhook_data
                current = await conn.fetchval(
                    "SELECT webhook_data FROM sessions WHERE id = $1",
                    session_id
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
            params = [session_id]
            param_num = 2
            
            for key, value in metadata.items():
                if key == "webhook_data":
                    updates.append(f"webhook_data = ${param_num}::jsonb")
                    params.append(value)
                elif key == "merge_request_url":
                    updates.append(f"merge_request_url = ${param_num}")
                    params.append(value)
                elif key == "merge_request_id":
                    updates.append(f"merge_request_id = ${param_num}")
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
                    SET {', '.join(updates)}, last_activity = CURRENT_TIMESTAMP
                    WHERE id = $1
                """
                await conn.execute(query, *params)
                log.debug(f"Updated metadata for session {session_id}")
    
    async def update_quality_metrics(self, session_id: str, metrics: Dict[str, Any]):
        """Update quality metrics for a session"""
        async with self.get_connection() as conn:
            await conn.execute(
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
                    last_activity = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                session_id,
                metrics.get("total_issues", 0),
                metrics.get("critical_issues", 0),
                metrics.get("major_issues", 0),
                metrics.get("bug_count", 0),
                metrics.get("vulnerability_count", 0),
                metrics.get("code_smell_count", 0),
                metrics.get("coverage"),
                metrics.get("duplicated_lines_density"),
                metrics.get("reliability_rating", "E")[:1],
                metrics.get("security_rating", "E")[:1],
                metrics.get("maintainability_rating", "E")[:1],
                json.dumps({"quality_metrics": metrics})
            )
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