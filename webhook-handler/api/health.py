"""Health check API for webhook handler"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any
from datetime import datetime
from utils.logger import log
from db.database import Database
from services.queue_publisher import QueuePublisher
import redis.asyncio as redis
from config import settings

router = APIRouter(tags=["health"])

def get_database() -> Database:
    """Get database instance from application state"""
    from main import app_state
    if not app_state.db:
        raise HTTPException(status_code=503, detail="Database not available")
    return app_state.db

@router.get("/")
async def health_check() -> Dict[str, Any]:
    """Basic health check"""
    return {
        "status": "healthy",
        "service": settings.service_name,
        "version": settings.version,
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/detailed")
async def detailed_health_check(
    db: Database = Depends(get_database)
) -> Dict[str, Any]:
    """Detailed health check with component status"""
    health_status = {
        "status": "healthy",
        "service": settings.service_name,
        "version": settings.version,
        "timestamp": datetime.utcnow().isoformat(),
        "components": {}
    }
    
    # Check database
    try:
        await db.health_check()
        health_status["components"]["database"] = "healthy"
    except Exception as e:
        health_status["components"]["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check queue
    try:
        publisher = QueuePublisher()
        await publisher.health_check()
        health_status["components"]["queue"] = "healthy"
    except Exception as e:
        health_status["components"]["queue"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check Redis cache
    try:
        r = redis.from_url(settings.redis_url)
        await r.ping()
        await r.close()
        health_status["components"]["cache"] = "healthy"
    except Exception as e:
        health_status["components"]["cache"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    return health_status

@router.get("/readiness")
async def readiness_check(
    db: Database = Depends(get_database)
) -> Dict[str, Any]:
    """Kubernetes readiness probe"""
    try:
        await db.health_check()
        return {"ready": True}
    except Exception as e:
        log.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail="Service not ready")

@router.get("/liveness")
async def liveness_check() -> Dict[str, Any]:
    """Kubernetes liveness probe"""
    return {"alive": True}