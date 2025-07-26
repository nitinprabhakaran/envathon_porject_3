import asyncpg
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import json
import os
from contextlib import asynccontextmanager
from loguru import logger

class SessionManager:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self._pool = None
    
    async def _get_pool(self):
        if not self._pool:
            self._pool = await asyncpg.create_pool(self.db_url, min_size=1, max_size=10)
        return self._pool
    
    @asynccontextmanager
    async def _get_connection(self):
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            yield conn
    
    async def create_or_get_session(
        self,
        session_id: str,
        project_id: str,
        pipeline_id: str,
        commit_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new session or return existing one"""
        async with self._get_connection() as conn:
            # Try to get existing active session for this pipeline
            existing = await conn.fetchrow(
                """
                SELECT * FROM sessions 
                WHERE pipeline_id = $1 AND project_id = $2 AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                pipeline_id, project_id
            )
            
            if existing:
                return dict(existing)
            
            # Create new session
            new_session = await conn.fetchrow(
                """
                INSERT INTO sessions (id, project_id, pipeline_id, commit_hash)
                VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                session_id, project_id, pipeline_id, commit_hash
            )
            
            return dict(new_session)
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID"""
        async with self._get_connection() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sessions WHERE id = $1",
                session_id
            )
            return dict(row) if row else None
    
    async def update_conversation(
        self,
        session_id: str,
        message: Dict[str, Any]
    ):
        """Add a message to conversation history"""
        async with self._get_connection() as conn:
            await conn.execute(
                """
                UPDATE sessions 
                SET conversation_history = conversation_history || $2::jsonb,
                    last_activity = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                session_id, json.dumps([message])
            )
    
    async def update_metadata(
        self,
        session_id: str,
        metadata: Dict[str, Any]
    ):
        """Update session metadata"""
        logger.info(f"update_metadata called with: {metadata}")
        async with self._get_connection() as conn:
            # Update specific fields
            if "error_signature" in metadata:
                await conn.execute(
                    "UPDATE sessions SET error_signature = $2 WHERE id = $1",
                    session_id, metadata["error_signature"]
                )
            
            if "failed_stage" in metadata:
                await conn.execute(
                    "UPDATE sessions SET failed_stage = $2 WHERE id = $1",
                    session_id, metadata["failed_stage"]
                )
            
            if "error_type" in metadata:
                await conn.execute(
                    "UPDATE sessions SET error_type = $2 WHERE id = $1",
                    session_id, metadata["error_type"]
                )
            
            if "webhook_data" in metadata:
                await conn.execute(
                    "UPDATE sessions SET webhook_data = $2 WHERE id = $1",
                    session_id, json.dumps(metadata["webhook_data"])
                )
            
            if "branch" in metadata:
                await conn.execute(
                    "UPDATE sessions SET branch = $2 WHERE id = $1",
                    session_id, metadata["branch"]
                )

            if "pipeline_source" in metadata:
                await conn.execute(
                    "UPDATE sessions SET pipeline_source = $2 WHERE id = $1",
                    session_id, metadata["pipeline_source"]
                )

            if "commit_sha" in metadata:
                await conn.execute(
                    "UPDATE sessions SET commit_sha = $2 WHERE id = $1",
                    session_id, metadata["commit_sha"]
                )

            if "job_name" in metadata:
                await conn.execute(
                    "UPDATE sessions SET job_name = $2 WHERE id = $1",
                    session_id, metadata["job_name"]
                )

            if "project_name" in metadata:
                await conn.execute(
                    "UPDATE sessions SET project_name = $2 WHERE id = $1",
                    session_id, metadata["project_name"]
                )
    
    async def add_applied_fix(
        self,
        session_id: str,
        fix_data: Dict[str, Any]
    ):
        """Record an applied fix"""
        async with self._get_connection() as conn:
            fix_data["applied_at"] = datetime.utcnow().isoformat()
            await conn.execute(
                """
                UPDATE sessions 
                SET applied_fixes = applied_fixes || $2::jsonb
                WHERE id = $1
                """,
                session_id, json.dumps([fix_data])
            )
    
    async def mark_fix_successful(
        self,
        session_id: str,
        fix_data: Dict[str, Any]
    ):
        """Mark a fix as successful"""
        async with self._get_connection() as conn:
            fix_data["confirmed_at"] = datetime.utcnow().isoformat()
            await conn.execute(
                """
                UPDATE sessions 
                SET successful_fixes = successful_fixes || $2::jsonb,
                    status = 'resolved'
                WHERE id = $1
                """,
                session_id, json.dumps([fix_data])
            )
    
    async def store_historical_fix(
        self,
        session_id: str,
        error_signature: str,
        fix_description: str,
        fix_type: str,
        confidence_score: float
    ) -> int:
        """Store a successful fix in historical fixes table"""
        async with self._get_connection() as conn:
            # Get session details
            session = await self.get_session(session_id)
            
            # Create hash of error signature
            import hashlib
            error_hash = hashlib.sha256(error_signature.encode()).hexdigest()
            
            # Store fix
            fix_id = await conn.fetchval(
                """
                INSERT INTO historical_fixes 
                (session_id, error_signature_hash, fix_description, fix_type, 
                 confidence_score, project_context, success_confirmed)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                session_id, error_hash, fix_description, fix_type,
                confidence_score, json.dumps({"project_id": session["project_id"]}), True
            )
            
            return fix_id
    
    async def get_active_sessions(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all active sessions"""
        async with self._get_connection() as conn:
            if project_id:
                rows = await conn.fetch(
                    """
                    SELECT * FROM sessions 
                    WHERE project_id = $1 AND status = 'active' 
                    AND expires_at > CURRENT_TIMESTAMP
                    ORDER BY last_activity DESC
                    """,
                    project_id
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM sessions 
                    WHERE status = 'active' AND expires_at > CURRENT_TIMESTAMP
                    ORDER BY last_activity DESC
                    """
                )
            
            return [dict(row) for row in rows]