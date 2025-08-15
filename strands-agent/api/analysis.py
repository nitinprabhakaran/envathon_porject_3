"""Analysis API endpoints for direct analysis requests"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from pydantic import BaseModel
from utils.logger import log
from db.session_manager import SessionManager
from agents.pipeline_agent import PipelineAgent
from agents.quality_agent import QualityAgent
from services.vector_store import VectorStore

router = APIRouter(prefix="/analysis", tags=["analysis"])

# Initialize components
session_manager = SessionManager()
pipeline_agent = PipelineAgent()
quality_agent = QualityAgent()
vector_store = VectorStore()

class AnalysisRequest(BaseModel):
    """Request model for analysis"""
    session_id: str
    analysis_type: str  # 'pipeline' or 'quality'
    force_refresh: bool = False

class SearchRequest(BaseModel):
    """Request model for searching previous fixes"""
    query: str
    project_id: str = None
    limit: int = 10

@router.post("/trigger")
async def trigger_analysis(request: AnalysisRequest):
    """Manually trigger analysis for a session"""
    try:
        session = await session_manager.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        log.info(f"Triggering {request.analysis_type} analysis for session {request.session_id}")
        
        # Get context
        context = await session_manager.get_session_context(request.session_id)
        
        # Run appropriate analysis
        if request.analysis_type == "quality":
            result = await quality_agent.analyze_quality_issues(context)
        else:
            result = await pipeline_agent.analyze_failure(context)
        
        # Update session with results
        await session_manager.update_session_metadata(
            request.session_id,
            {"analysis_result": result, "analysis_completed": True}
        )
        
        return {
            "status": "success",
            "session_id": request.session_id,
            "analysis_type": request.analysis_type,
            "result": result
        }
        
    except Exception as e:
        log.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/search-fixes")
async def search_previous_fixes(request: SearchRequest):
    """Search for similar previous fixes in vector store"""
    try:
        log.info(f"Searching for fixes: {request.query}")
        
        # Search in vector store
        results = await vector_store.search_similar_fixes(
            query=request.query,
            project_id=request.project_id,
            limit=request.limit
        )
        
        return {
            "status": "success",
            "query": request.query,
            "results": results,
            "count": len(results)
        }
        
    except Exception as e:
        log.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats/{project_id}")
async def get_project_stats(project_id: str):
    """Get analysis statistics for a project"""
    try:
        # Get sessions for project
        sessions = await session_manager.get_project_sessions(project_id)
        
        stats = {
            "total_sessions": len(sessions),
            "pipeline_failures": sum(1 for s in sessions if s.get("session_type") == "pipeline"),
            "quality_issues": sum(1 for s in sessions if s.get("session_type") == "quality"),
            "successful_fixes": sum(1 for s in sessions if s.get("fix_status") == "success"),
            "pending_fixes": sum(1 for s in sessions if s.get("fix_status") == "pending"),
            "failed_fixes": sum(1 for s in sessions if s.get("fix_status") == "failed")
        }
        
        return stats
        
    except Exception as e:
        log.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health_check():
    """Check analysis service health"""
    try:
        # Check vector store
        vector_health = await vector_store.health_check()
        
        # Check database
        db_health = await session_manager.health_check()
        
        return {
            "status": "healthy",
            "components": {
                "vector_store": vector_health,
                "database": db_health,
                "agents": "operational"
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }