"""Updated Strands Agent - Without Webhook Handling"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
from utils.logger import log
from config import settings
from api.sessions import router as session_router
from api.analysis import router as analysis_router
from db.session_manager import SessionManager
from services.queue_processor import QueueProcessor
from services.vector_store import VectorStore

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    log.info("Starting Strands Agent Service...")
    
    # Initialize database
    session_manager = SessionManager()
    await session_manager.init_pool()
    
    # Initialize vector store
    vector_store = VectorStore()
    await vector_store.init()
    
    # Start queue processor
    queue_processor = QueueProcessor()
    queue_task = asyncio.create_task(queue_processor.start())
    
    # Start cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup(session_manager))
    
    yield
    
    # Cleanup
    await queue_processor.stop()
    queue_task.cancel()
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
    title="Strands Agent Service",
    version="2.0.0",
    description="AI Agent for CI/CD failure analysis with vector store",
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

# Include routers (NO webhook router)
app.include_router(session_router)
app.include_router(analysis_router)

@app.get("/")
async def root():
    return {
        "service": "Strands Agent",
        "version": "2.0.0",
        "status": "operational",
        "features": ["analysis", "vector_store", "session_management"]
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)