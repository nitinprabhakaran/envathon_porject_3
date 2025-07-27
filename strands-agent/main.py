from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv
from loguru import logger
from api.webhook import webhook_router
from api.sonarqube_webhook import sonarqube_router
from api.routes import api_router

from api.webhook import webhook_router
from api.routes import api_router
from db.models import init_db
from vector.qdrant_client import init_vector_db

import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    logger.info("Starting CI/CD Failure Assistant...")
    
    try:
        logger.info("Initializing database...")
        await init_db()
        
        logger.info("Initializing vector database...")
        await init_vector_db()
        
        logger.info("Application started successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down application...")

app = FastAPI(
    title="CI/CD Failure Analysis Agent",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(webhook_router, prefix="/webhook", tags=["webhooks"])
app.include_router(api_router, prefix="/api", tags=["api"])

@app.get("/")
async def root():
    return {
        "name": "CI/CD Failure Analysis Agent",
        "version": "1.0.0",
        "status": "operational"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "vector_db": "connected"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)