from importlib import metadata
import asyncpg
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import json
import os
from contextlib import asynccontextmanager
from loguru import logger
import hashlib

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
                result = dict(existing)
                # Parse JSON fields
                for field in ['conversation_history', 'applied_fixes', 'successful_fixes', 'tools_called', 'user_feedback', 'webhook_data']:
                    if field in result and isinstance(result[field], str):
                        try:
                            result[field] = json.loads(result[field])
                        except:
                            result[field] = [] if field.endswith('history') or field.endswith('fixes') or field == 'tools_called' else {}
                return result
            
            # Create new session with empty conversation history and ACTIVE status
            new_session = await conn.fetchrow(
                """
                INSERT INTO sessions (id, project_id, pipeline_id, commit_sha, conversation_history, status, session_type)
                VALUES ($1, $2, $3, $4, $5, 'active', 'pipeline')
                RETURNING *
                """,
                session_id, project_id, pipeline_id, commit_hash, json.dumps([])
            )
            
            result = dict(new_session)
            # Parse JSON fields for new session
            for field in ['conversation_history', 'applied_fixes', 'successful_fixes', 'tools_called', 'user_feedback', 'webhook_data']:
                if field in result and isinstance(result[field], str):
                    try:
                        result[field] = json.loads(result[field])
                    except:
                        result[field] = [] if field.endswith('history') or field.endswith('fixes') or field == 'tools_called' else {}
            
            return result
    
    async def create_quality_session(
        self,
        session_id: str,
        project_id: str,
        project_name: str,
        quality_gate_status: str = "ERROR"
    ) -> Dict[str, Any]:
        """Create a new quality analysis session"""
        async with self._get_connection() as conn:
            new_session = await conn.fetchrow(
                """
                INSERT INTO sessions (id, project_id, project_name, session_type, 
                                    quality_gate_status, conversation_history, status)
                VALUES ($1, $2, $3, 'quality', $4, $5, 'active')
                RETURNING *
                """,
                session_id, project_id, project_name, quality_gate_status, json.dumps([])
            )
            
            result = dict(new_session)
            # Parse JSON fields
            for field in ['conversation_history', 'applied_fixes', 'successful_fixes', 'tools_called', 'user_feedback', 'webhook_data']:
                if field in result and isinstance(result[field], str):
                    try:
                        result[field] = json.loads(result[field])
                    except:
                        result[field] = [] if field.endswith('history') or field.endswith('fixes') or field == 'tools_called' else {}
            
            return result
    
    async def update_quality_metrics(
        self,
        session_id: str,
        total_issues: int,
        critical_issues: int,
        major_issues: int
    ):
        """Update quality metrics for a session"""
        async with self._get_connection() as conn:
            await conn.execute(
                """
                UPDATE sessions 
                SET total_issues = $2,
                    critical_issues = $3,
                    major_issues = $4,
                    last_activity = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                session_id, total_issues, critical_issues, major_issues
            )
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID"""
        async with self._get_connection() as conn:
            # Handle both string and UUID formats
            try:
                from uuid import UUID
                if isinstance(session_id, str):
                    session_uuid = UUID(session_id)
                else:
                    session_uuid = session_id
            except:
                logger.error(f"Invalid session ID format: {session_id}")
                return None
                
            row = await conn.fetchrow(
                "SELECT * FROM sessions WHERE id = $1",
                session_uuid
            )
            if not row:
                return None
                
            result = dict(row)
            # Parse JSON fields
            for field in ['conversation_history', 'applied_fixes', 'successful_fixes', 'tools_called', 'user_feedback', 'webhook_data']:
                if field in result and isinstance(result[field], str):
                    try:
                        result[field] = json.loads(result[field])
                    except:
                        result[field] = [] if field.endswith('history') or field.endswith('fixes') or field == 'tools_called' else {}
            
            return result
    
    async def update_conversation(
        self,
        session_id: str,
        message: Dict[str, Any]
    ):
        """Add a message to conversation history"""

        # Check for error patterns in assistant messages
        if message.get("role") == "assistant" and message.get("content"):
            if "ERROR IN TOOL CALL:" in message["content"]:
                logger.error(f"Tool call error detected in session {session_id}: {message['content']}")
                
        async with self._get_connection() as conn:
            # First get current conversation history
            current = await conn.fetchval(
                "SELECT conversation_history FROM sessions WHERE id = $1",
                session_id
            )
            
            if current:
                if isinstance(current, str):
                    try:
                        history = json.loads(current)
                    except:
                        history = []
                else:
                    history = current
            else:
                history = []
            
            # Append new message
            history.append(message)
            
            # Update with full history
            await conn.execute(
                """
                UPDATE sessions 
                SET conversation_history = $2::jsonb,
                    last_activity = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                session_id, json.dumps(history)
            )
            
            logger.info(f"Updated conversation for session {session_id}, history now has {len(history)} messages")
    
    async def update_metadata(
        self,
        session_id: str,
        metadata: Dict[str, Any]
    ):
        """Update session metadata"""
        logger.info(f"update_metadata called with: {list(metadata.keys())}")

        # Handle all_failed_jobs specially
        if "all_failed_jobs" in metadata:
            metadata["all_failed_jobs"] = json.dumps(metadata["all_failed_jobs"])

        async with self._get_connection() as conn:
            # Build update query dynamically
            update_fields = []
            params = [session_id]  # First parameter is always session_id
            param_count = 1
            
            field_mapping = {
                "error_signature": "error_signature",
                "failed_stage": "failed_stage",
                "error_type": "error_type",
                "branch": "branch",
                "pipeline_source": "pipeline_source",
                "commit_sha": "commit_hash",
                "job_name": "job_name",
                "project_name": "project_name",
                "merge_request_id": "merge_request_id",
                "pipeline_url": "pipeline_url",
                "project_key": "project_id",
            }
            
            for key, value in metadata.items():
                if key == "webhook_data":
                    param_count += 1
                    params.append(json.dumps(value))
                    update_fields.append(f"webhook_data = ${param_count}::jsonb")
                elif key in field_mapping:
                    param_count += 1
                    params.append(value)
                    update_fields.append(f"{field_mapping[key]} = ${param_count}")
            
            if update_fields:
                query = f"""
                    UPDATE sessions 
                    SET {', '.join(update_fields)},
                        last_activity = CURRENT_TIMESTAMP
                    WHERE id = $1
                """
                await conn.execute(query, *params)
                logger.info(f"Updated metadata for session {session_id}")
    
    async def add_applied_fix(
        self,
        session_id: str,
        fix_data: Dict[str, Any]
    ):
        """Record an applied fix"""
        async with self._get_connection() as conn:
            fix_data["applied_at"] = datetime.utcnow().isoformat()
            
            # Get current fixes
            current = await conn.fetchval(
                "SELECT applied_fixes FROM sessions WHERE id = $1",
                session_id
            )
            
            if current:
                if isinstance(current, str):
                    try:
                        fixes = json.loads(current)
                    except:
                        fixes = []
                else:
                    fixes = current
            else:
                fixes = []
            
            fixes.append(fix_data)
            
            await conn.execute(
                """
                UPDATE sessions 
                SET applied_fixes = $2::jsonb
                WHERE id = $1
                """,
                session_id, json.dumps(fixes)
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
            # Debug: First check what's in the database
            debug_rows = await conn.fetch(
                """
                SELECT id, status, expires_at, created_at, project_id, pipeline_id, session_type 
                FROM sessions 
                ORDER BY created_at DESC 
                LIMIT 5
                """
            )
            logger.info(f"Debug - Recent sessions: {[dict(r) for r in debug_rows]}")
            
            # Main query
            if project_id:
                rows = await conn.fetch(
                    """
                    SELECT * FROM sessions 
                    WHERE project_id = $1 AND status = 'active'
                    ORDER BY last_activity DESC
                    """,
                    project_id
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM sessions 
                    WHERE status = 'active'
                    ORDER BY last_activity DESC
                    """
                )
            
            logger.info(f"Found {len(rows)} active sessions")
            
            results = []
            for row in rows:
                result = dict(row)
                # Parse JSON fields
                for field in ['conversation_history', 'applied_fixes', 'successful_fixes', 'tools_called', 'user_feedback', 'webhook_data']:
                    if field in result and isinstance(result[field], str):
                        try:
                            result[field] = json.loads(result[field])
                        except:
                            result[field] = [] if field.endswith('history') or field.endswith('fixes') or field == 'tools_called' else {}
                results.append(result)
            
            return results
    
    async def check_existing_quality_session(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Check if there's an existing active quality session for a project"""
        async with self._get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM sessions 
                WHERE project_id = $1 
                AND session_type = 'quality' 
                AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                project_id
            )

            if row:
                result = dict(row)
                # Parse JSON fields
                for field in ['conversation_history', 'applied_fixes', 'successful_fixes', 'tools_called', 'user_feedback', 'webhook_data']:
                    if field in result and isinstance(result[field], str):
                        try:
                            result[field] = json.loads(result[field])
                        except:
                            result[field] = [] if field.endswith('history') or field.endswith('fixes') or field == 'tools_called' else {}
                return result

            return None