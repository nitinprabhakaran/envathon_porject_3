import os
import asyncpg
from loguru import logger

async def init_db():
    """Initialize database connection and ensure tables exist"""
    db_url = os.getenv("DATABASE_URL")
    
    try:
        # Create connection
        conn = await asyncpg.connect(db_url)
        
        # Check if tables exist
        tables_exist = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'sessions')"
        )
        
        if not tables_exist:
            logger.warning("Database tables not found. Please run init.sql to create tables.")
        else:
            logger.info("Database tables verified")
        
        await conn.close()
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise