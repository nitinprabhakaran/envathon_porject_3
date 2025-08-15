"""Webhook Handler Service - Main Application"""
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import hmac
from typing import Optional
from utils.logger import log
from config import settings
from api.webhooks import router as webhook_router
from api.subscriptions import router as subscription_router
from api.health import router as health_router
from services.event_processor import EventProcessor
from db.database import Database

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    log.info("Starting Webhook Handler Service...")
    
    # Initialize database
    db = Database()
    await db.init()
    
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
            log.info("Running periodic cleanup")
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Cleanup error: {e}")

# Create app
app = FastAPI(
    title="CI/CD Webhook Handler",
    version="2.0.0",
    description="Webhook handler with subscription management",
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

# Include routers
app.include_router(webhook_router)
app.include_router(subscription_router)
app.include_router(health_router)

@app.get("/")
async def root():
    return {
        "service": "Webhook Handler",
        "version": "2.0.0",
        "status": "operational"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)