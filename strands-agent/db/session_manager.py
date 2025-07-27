"""Session management for persistent conversations"""
import asyncpg
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from utils.logger import log
from config import settings

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
        async with self.get_connection() as conn:
            session = await conn.fetchrow(
                """
                INSERT INTO sessions (
                    id, session_type, project_id, status,
                    project_name, branch, pipeline_id, 
                    pipeline_url, job_name, failed_stage,
                    quality_gate_status, webhook_data
                ) VALUES ($1, $2, $3, 'active', $4, $5, $6, $7, $8, $9, $10, $11)
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
                json.dumps(metadata.get("webhook_data", {}))
            )
            log.info(f"Created {session_type} session {session_id}")
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
                for field in ['conversation_history', 'webhook_data']:
                    if field in result and isinstance(result[field], str):
                        try:
                            result[field] = json.loads(result[field])
                        except:
                            result[field] = [] if field == 'conversation_history' else {}
                return result
            return None
    
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
                for field in ['conversation_history', 'webhook_data']:
                    if field in result and isinstance(result[field], str):
                        try:
                            result[field] = json.loads(result[field])
                        except:
                            result[field] = [] if field == 'conversation_history' else {}
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