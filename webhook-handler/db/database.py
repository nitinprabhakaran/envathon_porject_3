"""Database interface for webhook handler"""
import asyncpg
from typing import Dict, Any, List, Optional
from datetime import datetime
from utils.logger import log
from config import settings
import json

class Database:
    """Database operations for webhook handler"""
    
    def __init__(self):
        self.pool = None
    
    async def init(self):
        """Initialize database connection pool"""
        try:
            # For local development, use minimal pooling
            if hasattr(settings, 'environment') and settings.environment == 'local':
                self.pool = await asyncpg.create_pool(
                    settings.database_url,
                    min_size=1,
                    max_size=2,
                    command_timeout=60
                )
                log.info("Database pool initialized for local development (min: 1, max: 2)")
            else:
                # Production-style pooling for other environments
                self.pool = await asyncpg.create_pool(
                    settings.database_url,
                    min_size=settings.db_pool_min_size,
                    max_size=settings.db_pool_max_size,
                    command_timeout=60
                )
                log.info(f"Database pool initialized (min: {settings.db_pool_min_size}, max: {settings.db_pool_max_size})")
        except Exception as e:
            log.error(f"Failed to initialize database: {e}")
            raise
    
    async def create_session(self, session_data: Dict[str, Any]) -> str:
        """Create a new session"""
        query = """
            INSERT INTO sessions (
                id, session_type, project_id, project_name,
                pipeline_id, pipeline_status, pipeline_url, 
                job_name, job_id, branch, failed_stage, commit_sha,
                sonarqube_key, quality_gate_status, mr_id, mr_title, mr_url,
                unique_id, subscription_id, webhook_data, created_at, expires_at, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23)
            RETURNING id
        """
        
        async with self.pool.acquire() as conn:
            session_id = await conn.fetchval(
                query,
                session_data["id"],  # Use 'id' instead of 'session_id'
                session_data["session_type"],
                session_data["project_id"],
                session_data.get("project_name"),
                session_data.get("pipeline_id"),
                session_data.get("pipeline_status"),
                session_data.get("pipeline_url"),
                session_data.get("job_name"),
                session_data.get("job_id"),
                session_data.get("branch"),
                session_data.get("failed_stage"),
                session_data.get("commit_sha"),
                session_data.get("sonarqube_key"),
                session_data.get("quality_gate_status"),
                session_data.get("mr_id"),
                session_data.get("mr_title"),
                session_data.get("mr_url"),
                session_data.get("unique_id"),
                session_data.get("subscription_id"),
                json.dumps(session_data.get("webhook_data", {})),
                session_data["created_at"],
                session_data["expires_at"],
                session_data.get("status", "active")
            )
            return session_id
    
    async def get_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        """Get subscription details"""
        query = """
            SELECT * FROM webhook_subscriptions 
            WHERE subscription_id = $1 AND expires_at > NOW()
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, subscription_id)
            return dict(row) if row else None
    
    async def create_subscription(self, subscription_data: Dict[str, Any]) -> str:
        """Create a new subscription"""
        query = """
            INSERT INTO webhook_subscriptions (
                subscription_id, project_id, project_type, project_url,
                webhook_url, webhook_secret, webhook_ids, 
                status, created_at, expires_at, api_key, metadata, webhook_events
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING subscription_id
        """
        
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query,
                subscription_data["subscription_id"],
                subscription_data["project_id"],
                subscription_data["project_type"],
                subscription_data["project_url"],
                subscription_data["webhook_url"],
                subscription_data["webhook_secret"],
                json.dumps(subscription_data.get("webhook_ids", [])),
                subscription_data["status"],
                subscription_data["created_at"],
                subscription_data["expires_at"],
                subscription_data.get("api_key", "default"),
                json.dumps(subscription_data.get("metadata", {})),
                json.dumps(subscription_data.get("webhook_events", []))
            )
    
    async def list_subscriptions(
        self, 
        api_key: str, 
        status: str = "active", 
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List subscriptions for a given API key"""
        query = """
            SELECT subscription_id, project_id, project_type, project_url,
                   webhook_url, webhook_ids, status, created_at, expires_at,
                   webhook_events, metadata
            FROM webhook_subscriptions 
            WHERE api_key = $1 AND status = $2
            ORDER BY created_at DESC
            LIMIT $3
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, api_key, status, limit)
            return [
                {
                    **dict(row),
                    "webhook_ids": json.loads(row["webhook_ids"]) if row["webhook_ids"] else [],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {}
                }
                for row in rows
            ]
    
    async def find_subscription_by_project(
        self, 
        project_id: str, 
        project_type: str,
        status: str = "active"
    ) -> Optional[Dict[str, Any]]:
        """Find subscription by project details for webhook authentication"""
        query = """
            SELECT subscription_id, project_id, project_type, project_url,
                   webhook_url, webhook_secret, webhook_ids, status, created_at, expires_at,
                   webhook_events, metadata, access_token
            FROM webhook_subscriptions 
            WHERE project_id = $1 AND project_type = $2 AND status = $3
            ORDER BY created_at DESC
            LIMIT 1
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, project_id, project_type, status)
            if row:
                return {
                    **dict(row),
                    "webhook_ids": json.loads(row["webhook_ids"]) if row["webhook_ids"] else [],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {}
                }
            return None
    
    async def update_subscription(
        self, 
        subscription_id: str, 
        update_data: Dict[str, Any]
    ) -> bool:
        """Update subscription data"""
        set_clauses = []
        values = []
        param_count = 1
        
        for key, value in update_data.items():
            if key in ["expires_at", "status", "last_refreshed"]:
                set_clauses.append(f"{key} = ${param_count}")
                values.append(value)
                param_count += 1
        
        if not set_clauses:
            return False
        
        query = f"""
            UPDATE webhook_subscriptions 
            SET {', '.join(set_clauses)}
            WHERE subscription_id = ${param_count}
        """
        values.append(subscription_id)
        
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, *values)
            return result != "UPDATE 0"
    
    async def health_check(self) -> bool:
        """Check database health"""
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            log.error(f"Database health check failed: {e}")
            return False
    
    async def find_session_by_unique_id(
        self, 
        session_type: str, 
        project_id: str, 
        unique_id: str
    ) -> Optional[Dict[str, Any]]:
        """Find existing session by unique identifier to prevent duplicates"""
        if session_type == "pipeline":
            # For GitLab: unique_id is pipeline_id
            query = """
                SELECT id as session_id, session_type, project_id, status, created_at
                FROM sessions 
                WHERE session_type = $1 AND project_id = $2 AND pipeline_id = $3 AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
            """
        elif session_type == "quality":
            # For SonarQube: unique_id is project_key:branch
            query = """
                SELECT id as session_id, session_type, project_id, status, created_at
                FROM sessions 
                WHERE session_type = $1 AND project_id = $2 AND unique_id = $3 AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
            """
        else:
            return None
        
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, session_type, project_id, unique_id)
                if row:
                    return dict(row)
        except Exception as e:
            log.error(f"Error finding session by unique ID: {e}")
        
        return None
    
    async def update_session(
        self, 
        session_id: str, 
        update_data: Dict[str, Any]
    ) -> bool:
        """Update session data"""
        set_clauses = []
        values = []
        param_count = 1
        
        # Convert webhook_data to JSON if present
        if "webhook_data" in update_data:
            update_data["webhook_data"] = json.dumps(update_data["webhook_data"])
        
        for key, value in update_data.items():
            set_clauses.append(f"{key} = ${param_count}")
            values.append(value)
            param_count += 1
        
        if not set_clauses:
            return False
        
        query = f"""
            UPDATE sessions 
            SET {', '.join(set_clauses)}
            WHERE id = ${param_count}
        """
        values.append(session_id)
        
        try:
            async with self.pool.acquire() as conn:
                result = await conn.execute(query, *values)
                return result != "UPDATE 0"
        except Exception as e:
            log.error(f"Error updating session {session_id}: {e}")
            return False
    
    async def close(self):
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()
            log.info("Database pool closed")