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
    
    async def create_session(
        self,
        session_id: str,
        session_type: str,
        project_id: str,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create new session"""
        # Calculate expiration based on config
        expires_at = datetime.utcnow() + timedelta(minutes=settings.session_timeout_minutes)
        
        async with self.get_connection() as conn:
            session = await conn.fetchrow(
                """
                INSERT INTO sessions (
                    id, session_type, project_id, status,
                    project_name, branch, pipeline_id, 
                    pipeline_url, job_name, failed_stage,
                    quality_gate_status, webhook_data, expires_at
                ) VALUES ($1, $2, $3, 'active', $4, $5, $6, $7, $8, $9, $10, $11, $12)
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
                expires_at  # Set expires_at based on config
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
            gitlab_project_id=session.get('project_id'),  # For quality sessions
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
    
    async def update_session_metadata(self, session_id: str, metadata: Dict[str, Any]):
        """Update session metadata"""
        async with self.get_connection() as conn:
            # Build update query dynamically
            updates = []
            params = [session_id]
            param_num = 2
            
            field_mapping = {
                "merge_request_url": "merge_request_url",
                "merge_request_id": "merge_request_id",
                "fixes_applied": "fixes_applied"
            }
            
            for key, value in metadata.items():
                if key in field_mapping:
                    updates.append(f"{field_mapping[key]} = ${param_num}")
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
    
    async def store_fix_result(self, session_id: str, mr_url: str, mr_id: str, files_changed: Dict[str, str]):
        """Store successful fix information"""
        async with self.get_connection() as conn:
            # Update session with MR info
            await conn.execute(
                """
                UPDATE sessions 
                SET merge_request_url = $2, 
                    merge_request_id = $3,
                    fixes_applied = $4::jsonb
                WHERE id = $1
                """,
                session_id, mr_url, mr_id, json.dumps(files_changed)
            )
            
            # Store in historical fixes
            session = await self.get_session(session_id)
            error_signature = session.get('error_signature', '')
            
            if error_signature:
                await conn.execute(
                    """
                    INSERT INTO historical_fixes 
                    (session_id, error_signature_hash, fix_description, fix_type, success_confirmed, project_context)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    session_id, 
                    hashlib.sha256(error_signature.encode()).hexdigest(),
                    f"MR: {mr_url}",
                    session['session_type'],
                    False,  # Will be updated when pipeline passes
                    json.dumps({'files': list(files_changed.keys())})
                )

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
    
    async def track_fix_attempt(self, session_id: str, mr_id: str, branch_name: str, fix_content: Dict[str, str]):
        """Track a fix attempt for iterative resolution"""
        async with self.get_connection() as conn:
            # Get current fix attempts
            current = await conn.fetchval(
                "SELECT webhook_data FROM sessions WHERE id = $1",
                session_id
            )
            
            webhook_data = json.loads(current) if current else {}
            fix_attempts = webhook_data.get('fix_attempts', [])
            
            fix_attempts.append({
                'mr_id': mr_id,
                'branch': branch_name,
                'timestamp': datetime.utcnow().isoformat(),
                'files_changed': list(fix_content.keys()),
                'status': 'pending'
            })
            
            webhook_data['fix_attempts'] = fix_attempts
            
            await conn.execute(
                "UPDATE sessions SET webhook_data = $2::jsonb WHERE id = $1",
                session_id, json.dumps(webhook_data)
            )

    async def get_fix_attempts(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all fix attempts for a session"""
        session = await self.get_session(session_id)
        return session.get('webhook_data', {}).get('fix_attempts', [])

    async def check_iteration_limit(self, session_id: str, limit: int = 5) -> bool:
        """Check if we've reached the iteration limit"""
        attempts = await self.get_fix_attempts(session_id)
        return len(attempts) >= limit
    
    async def store_analyzed_files(self, session_id: str, file_changes: Dict[str, Any]):
        """Store analyzed file paths and proposed changes"""
        async with self.get_connection() as conn:
            # Get current webhook data
            current = await conn.fetchval(
                "SELECT webhook_data FROM sessions WHERE id = $1",
                session_id
            )

            webhook_data = json.loads(current) if current else {}
            webhook_data['analyzed_files'] = {
                'timestamp': datetime.utcnow().isoformat(),
                'files': file_changes.get('files', []),
                'changes': file_changes.get('changes', {})
            }

            await conn.execute(
                "UPDATE sessions SET webhook_data = $2::jsonb WHERE id = $1",
                session_id, json.dumps(webhook_data)
            )
            log.info(f"Stored analyzed files for session {session_id}: {file_changes.get('files', [])}")

    async def get_analyzed_files(self, session_id: str) -> Dict[str, Any]:
        """Get stored analyzed file information"""
        session = await self.get_session(session_id)
        if session:
            return session.get('webhook_data', {}).get('analyzed_files', {})
        return {}
    
    async def mark_session_resolved(self, session_id: str):
        """Mark session as resolved when fix is successfully applied"""
        async with self.get_connection() as conn:
            await conn.execute(
                """
                UPDATE sessions 
                SET status = 'resolved',
                    last_activity = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                session_id
            )
            log.info(f"Marked session {session_id} as resolved")

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