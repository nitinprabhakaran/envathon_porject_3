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
            self.pool = await asyncpg.create_pool(
                settings.database_url,
                min_size=10,
                max_size=settings.db_pool_size,
                command_timeout=60
            )
            log.info("Database pool initialized")
        except Exception as e:
            log.error(f"Failed to initialize database: {e}")
            raise
    
    async def create_session(self, session_data: Dict[str, Any]) -> str:
        """Create a new session"""
        query = """
            INSERT INTO sessions (
                id, session_type, project_id, project_name,
                pipeline_id, pipeline_status, branch, 
                subscription_id, webhook_data, created_at, expires_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id
        """
        
        async with self.pool.acquire() as conn:
            session_id = await conn.fetchval(
                query,
                session_data["session_id"],
                session_data["session_type"],
                session_data["project_id"],
                session_data.get("project_name"),
                session_data.get("pipeline_id"),
                session_data.get("pipeline_status"),
                session_data.get("branch"),
                session_data.get("subscription_id"),
                json.dumps(session_data.get("webhook_data", {})),
                session_data["created_at"],
                session_data["expires_at"]
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
                status, created_at, expires_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
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
                json.dumps(subscription_data["webhook_ids"]),
                subscription_data["status"],
                subscription_data["created_at"],
                subscription_data["expires_at"]
            )
    
    async def health_check(self) -> bool:
        """Check database health"""
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            log.error(f"Database health check failed: {e}")
            return False
    
    async def close(self):
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()
            log.info("Database pool closed")