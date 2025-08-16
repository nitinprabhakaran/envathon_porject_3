"""Optimized Webhook Handler Service - Main Application"""
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


class AppState:
    """Application state management"""
    def __init__(self):
        self.db: Optional[Database] = None
        self.event_processor: Optional[EventProcessor] = None
        self.cleanup_task: Optional[asyncio.Task] = None
        self.health_check_task: Optional[asyncio.Task] = None


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Optimized application lifespan management with proper resource handling"""
    log.info("Starting Webhook Handler Service...")
    
    try:
        # Initialize database with connection pooling
        app_state.db = Database()
        await app_state.db.init()
        log.info("Database initialized successfully")
        
        # Initialize event processor
        app_state.event_processor = EventProcessor()
        log.info("Event processor initialized")
        
        # Start background tasks with proper error handling
        app_state.cleanup_task = asyncio.create_task(
            periodic_cleanup(), 
            name="cleanup_task"
        )
        
        app_state.health_check_task = asyncio.create_task(
            periodic_health_check(),
            name="health_check_task"
        )
        
        log.info("Background tasks started successfully")
        
        yield
        
    except Exception as e:
        log.error(f"Failed to start application: {e}")
        raise
    finally:
        # Graceful shutdown
        log.info("Shutting down application...")
        
        # Cancel background tasks
        for task in [app_state.cleanup_task, app_state.health_check_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    log.error(f"Error during task cleanup: {e}")
        
        # Close database connections
        if app_state.db:
            await app_state.db.close()
            log.info("Database connections closed")
        
        log.info("Shutdown complete")


async def periodic_cleanup():
    """Optimized periodic cleanup with configurable intervals"""
    cleanup_interval = getattr(settings, 'cleanup_interval', 3600)  # 1 hour default
    
    while True:
        try:
            await asyncio.sleep(cleanup_interval)
            
            if app_state.db:
                log.info("Running periodic cleanup")
                
                # Add actual cleanup operations here
                # await app_state.db.cleanup_expired_sessions()
                # await app_state.db.cleanup_old_events()
                
                log.info("Periodic cleanup completed")
            else:
                log.warning("Database not available for cleanup")
                
        except asyncio.CancelledError:
            log.info("Cleanup task cancelled")
            break
        except Exception as e:
            log.error(f"Cleanup error: {e}")
            # Continue running even if cleanup fails
            await asyncio.sleep(60)  # Wait before retrying


async def periodic_health_check():
    """Periodic health checks for external dependencies"""
    health_check_interval = getattr(settings, 'health_check_interval', 300)  # 5 minutes
    
    while True:
        try:
            await asyncio.sleep(health_check_interval)
            
            # Check database health
            if app_state.db:
                db_healthy = await app_state.db.health_check()
                if not db_healthy:
                    log.warning("Database health check failed")
            
            # Add other health checks as needed
            # - Check GitLab API connectivity
            # - Check SonarQube API connectivity
            # - Check queue service health
            
        except asyncio.CancelledError:
            log.info("Health check task cancelled")
            break
        except Exception as e:
            log.error(f"Health check error: {e}")
            await asyncio.sleep(60)


# Create optimized FastAPI app
app = FastAPI(
    title="CI/CD Webhook Handler",
    description="Optimized webhook handler for CI/CD pipeline events",
    version="2.0.0",
    lifespan=lifespan,
    # Performance optimizations
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url="/redoc" if settings.environment == "development" else None,
)

# Optimized CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for better error tracking"""
    log.error(f"Unhandled exception in {request.method} {request.url}: {exc}", exc_info=True)
    return HTTPException(
        status_code=500,
        detail="Internal server error. Please check logs for details."
    )


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log requests for debugging and monitoring"""
    start_time = asyncio.get_event_loop().time()
    
    response = await call_next(request)
    
    process_time = asyncio.get_event_loop().time() - start_time
    
    # Log slow requests
    if process_time > 1.0:
        log.warning(
            f"Slow request: {request.method} {request.url} "
            f"took {process_time:.2f}s - Status: {response.status_code}"
        )
    else:
        log.debug(
            f"{request.method} {request.url} - "
            f"{process_time:.3f}s - Status: {response.status_code}"
        )
    
    return response


# Include routers
app.include_router(health_router, prefix="/health", tags=["health"])
app.include_router(webhook_router, prefix="/webhooks", tags=["webhooks"])
app.include_router(subscription_router, prefix="/subscriptions", tags=["subscriptions"])


@app.get("/")
async def root():
    """Root endpoint with service information"""
    return {
        "service": "CI/CD Webhook Handler",
        "version": "2.0.0",
        "status": "running",
        "features": [
            "Webhook processing",
            "Event subscription management", 
            "Automatic cleanup",
            "Health monitoring"
        ]
    }


# Startup event for additional initialization
@app.on_event("startup")
async def startup_event():
    """Additional startup tasks"""
    log.info(f"Webhook Handler started in {settings.environment} mode")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=settings.environment == "development",
        log_level="info"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)