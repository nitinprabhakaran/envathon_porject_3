from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv

from api.webhook import webhook_router
from api.routes import api_router
from db.models import init_db
from vector.qdrant_client import init_vector_db
from mcp.integrated_runner import MCPManager

load_dotenv()

# Global MCP manager instance
mcp_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Initializing database...")
    await init_db()
    
    print("Initializing vector database...")
    await init_vector_db()
    
    print("Starting MCP servers...")
    global mcp_manager
    mcp_manager = MCPManager()
    await mcp_manager.start()
    
    yield
    
    # Shutdown
    print("Stopping MCP servers...")
    await mcp_manager.stop()

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

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "mcp_servers": {
            "gitlab": mcp_manager.gitlab_healthy if mcp_manager else False,
            "sonarqube": mcp_manager.sonar_healthy if mcp_manager else False
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)