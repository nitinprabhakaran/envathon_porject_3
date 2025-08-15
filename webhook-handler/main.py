"""Webhook Handler Service - Main Application"""
from fastapi import FastAPI, Depends, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import hmac
import hashlib
from typing import Optional
from utils.logger import log
from config import settings
from api.webhooks import router as webhook_router
from api.subscriptions import router as subscription_router
from api.health import router as health_router
from services.event_processor import EventProcessor
from db.database import Database
from services.vector_store import VectorStore

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    log.info("Starting Webhook Handler Service...")
    
    # Initialize database
    db = Database()
    await db.init()
    
    # Initialize vector store
    vector_store = VectorStore()
    await vector_store.init()
    
    # Initialize event processor
    event_processor = EventProcessor()
    
    # Start background tasks
    cleanup_task = asyncio.create_task(periodic_cleanup())
    
    yield
    
    # Cleanup
    cleanup_task.cancel()
    await db.close()
    log.info("Shutting down...")

async def periodic_cleanup():
    """Periodic cleanup of expired sessions and events"""
    while True:
        try:
            await asyncio.sleep(3600)  # Every hour
            # Cleanup logic here
            log.info("Running periodic cleanup")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Cleanup error: {e}")

# Create app
app = FastAPI(
    title="CI/CD Webhook Handler",
    version="2.0.0",
    description="Webhook handler with subscription management for CI/CD failure analysis",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security dependency for webhook authentication
async def verify_webhook_signature(
    request: Request,
    x_gitlab_token: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),  # GitHub format
    x_sonarqube_webhook_secret: Optional[str] = Header(None)
):
    """Verify webhook signature/token"""
    if settings.webhook_auth_enabled:
        # Check GitLab token
        if x_gitlab_token:
            if not hmac.compare_digest(x_gitlab_token, settings.gitlab_webhook_secret):
                raise HTTPException(status_code=401, detail="Invalid GitLab webhook token")
            return
        
        # Check SonarQube secret
        if x_sonarqube_webhook_secret:
            if not hmac.compare_digest(x_sonarqube_webhook_secret, settings.sonarqube_webhook_secret):
                raise HTTPException(status_code=401, detail="Invalid SonarQube webhook secret")
            return
        
        # Check HMAC signature (GitHub style, can be used for additional security)
        if x_hub_signature_256:
            body = await request.body()
            expected = hmac.new(
                settings.webhook_hmac_secret.encode(),
                body,
                hashlib.sha256
            ).hexdigest()
            provided = x_hub_signature_256.replace("sha256=", "")
            if not hmac.compare_digest(expected, provided):
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
            return
        
        # No valid authentication provided
        raise HTTPException(status_code=401, detail="Webhook authentication required")

# Include routers
app.include_router(webhook_router, dependencies=[Depends(verify_webhook_signature)])
app.include_router(subscription_router, prefix="/api/v1")
app.include_router(health_router, prefix="/health")

@app.get("/")
async def root():
    return {
        "service": "Webhook Handler",
        "version": "2.0.0",
        "status": "operational",
        "endpoints": {
            "webhooks": "/webhooks/*",
            "subscriptions": "/api/v1/subscriptions",
            "health": "/health/ready"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)