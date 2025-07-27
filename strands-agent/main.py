"""Main FastAPI application"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
from utils.logger import log
from config import settings
from api.webhooks import router as webhook_router
from api.sessions import router as session_router
from db.session_manager import SessionManager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    log.info("Starting CI/CD Failure Assistant...")
    
    # Initialize database
    session_manager = SessionManager()
    await session_manager.init_pool()
    
    # Start cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup(session_manager))
    
    yield
    
    # Cleanup
    cleanup_task.cancel()
    log.info("Shutting down...")

async def periodic_cleanup(session_manager: SessionManager):
    """Periodically clean up expired sessions"""
    while True:
        try:
            await asyncio.sleep(3600)  # Every hour
            await session_manager.cleanup_expired_sessions()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Cleanup error: {e}")

# Create app
app = FastAPI(
    title="CI/CD Failure Assistant",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(webhook_router)
app.include_router(session_router)

@app.get("/")
async def root():
    return {
        "name": "CI/CD Failure Assistant",
        "version": "1.0.0",
        "status": "operational"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)