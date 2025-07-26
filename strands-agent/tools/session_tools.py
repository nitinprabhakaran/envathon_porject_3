import os
from typing import Dict, Any, List, Optional
from strands import tool
from loguru import logger
import hashlib
from datetime import datetime

from db.session_manager import SessionManager
from vector.qdrant_client import QdrantManager

def get_current_session_id() -> Optional[str]:
    """Get session ID from current agent context"""
    try:
        # Try to get from tool's execution context
        import inspect
        frame = inspect.currentframe()
        while frame:
            frame_locals = frame.f_locals
            if 'self' in frame_locals:
                agent = frame_locals['self']
                if hasattr(agent, 'session_state'):
                    return agent.session_state.get("session_id")
            frame = frame.f_back
    except:
        pass
    return None

@tool
async def get_session_context(session_id: Optional[str] = None) -> Dict[str, Any]:
    """Get full session context and history
    
    Args:
        session_id: Session ID (will try to get from context if not provided)
    
    Returns:
        Full session context including conversation history
    """
    if not session_id:
        session_id = get_current_session_id()
        
    if not session_id:
        return {"error": "Session ID not found in context"}
    
    session_manager = SessionManager()
    session = await session_manager.get_session(session_id)
    
    if not session:
        return {"error": "Session not found", "session_id": session_id}
    
    return {
        "session_id": session_id,
        "project_id": session["project_id"],
        "pipeline_id": session["pipeline_id"],
        "status": session["status"],
        "created_at": str(session["created_at"]),
        "last_activity": str(session["last_activity"]),
        "conversation_history": session["conversation_history"],
        "applied_fixes": session["applied_fixes"],
        "successful_fixes": session["successful_fixes"],
        "error_signature": session.get("error_signature"),
        "failed_stage": session.get("failed_stage"),
        "tokens_used": session.get("tokens_used", 0)
    }

@tool
async def update_session_state(
    update_type: str,
    data: Dict[str, Any],
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """Update session state
    
    Args:
        update_type: Type of update (applied_fix, successful_fix, metadata)
        data: Data to update
        session_id: Session ID (will try to get from context if not provided)
    
    Returns:
        Update confirmation
    """
    if not session_id:
        session_id = get_current_session_id()
        
    if not session_id:
        return {"error": "Session ID not found in context"}
    
    session_manager = SessionManager()
    
    try:
        if update_type == "applied_fix":
            await session_manager.add_applied_fix(session_id, data)
        elif update_type == "successful_fix":
            await session_manager.mark_fix_successful(session_id, data)
        elif update_type == "metadata":
            await session_manager.update_metadata(session_id, data)
        else:
            return {"error": f"Unknown update type: {update_type}"}
        
        return {
            "status": "success",
            "update_type": update_type,
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to update session state: {e}")
        return {"error": str(e)}

@tool
async def search_similar_errors(
    error_signature: str,
    project_id: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Search for similar historical errors
    
    Args:
        error_signature: Error signature to search for
        project_id: Project ID for scoped search
        limit: Maximum number of results
    
    Returns:
        List of similar errors with their fixes
    """
    qdrant = QdrantManager()
    
    try:
        results = await qdrant.search_similar_errors(
            error_signature=error_signature,
            project_id=project_id,
            limit=limit
        )
        
        # Enrich results with additional context
        enriched_results = []
        for result in results:
            payload = result.get("payload", {})
            enriched = {
                "similarity_score": result.get("score", 0),
                "error_signature": payload.get("error_signature", ""),
                "fix_description": payload.get("fix_description", ""),
                "fix_type": payload.get("fix_type", ""),
                "confidence": payload.get("confidence", 0),
                "success_count": payload.get("success_count", 0),
                "failure_count": payload.get("failure_count", 0),
                "created_at": payload.get("created_at", ""),
                "project_id": payload.get("project_id", "")
            }
            
            # Calculate success rate
            total_attempts = enriched["success_count"] + enriched["failure_count"]
            if total_attempts > 0:
                enriched["success_rate"] = enriched["success_count"] / total_attempts
            else:
                enriched["success_rate"] = 0
            
            enriched_results.append(enriched)
        
        # Sort by similarity and success rate
        enriched_results.sort(
            key=lambda x: (x["similarity_score"] * 0.7 + x["success_rate"] * 0.3),
            reverse=True
        )
        
        return enriched_results
        
    except Exception as e:
        logger.error(f"Failed to search similar errors: {e}")
        return [{"error": str(e)}]

@tool
async def store_successful_fix(
    fix_description: str,
    fix_type: str,
    confidence_score: float,
    error_signature: Optional[str] = None,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """Store a successful fix for future reference
    
    Args:
        fix_description: Description of the fix
        fix_type: Type of fix (dependency, config, code, infrastructure)
        confidence_score: Confidence in the fix (0.0 to 1.0)
        error_signature: Error signature (will extract from session if not provided)
        session_id: Session ID (will try to get from context if not provided)
    
    Returns:
        Storage confirmation
    """
    if not session_id:
        session_id = get_current_session_id()
        
    if not session_id:
        return {"error": "Session ID not found in context"}
    
    session_manager = SessionManager()
    qdrant = QdrantManager()
    
    try:
        # Get session details
        session = await session_manager.get_session(session_id)
        if not session:
            return {"error": "Session not found"}
        
        # Use provided error signature or get from session
        if not error_signature:
            error_signature = session.get("error_signature", "")
        
        if not error_signature:
            return {"error": "No error signature available"}
        
        # Store in database
        fix_id = await session_manager.store_historical_fix(
            session_id=session_id,
            error_signature=error_signature,
            fix_description=fix_description,
            fix_type=fix_type,
            confidence_score=confidence_score
        )
        
        # Store in vector database
        project_context = {
            "project_id": session["project_id"],
            "fix_type": fix_type,
            "confidence": confidence_score,
            "session_id": session_id
        }
        
        await qdrant.store_successful_fix(
            error_signature=error_signature,
            fix_description=fix_description,
            project_context=project_context
        )
        
        return {
            "status": "success",
            "fix_id": fix_id,
            "message": "Fix stored successfully for future reference",
            "error_signature": error_signature[:50] + "..." if len(error_signature) > 50 else error_signature
        }
        
    except Exception as e:
        logger.error(f"Failed to store successful fix: {e}")
        return {"error": str(e)}

@tool
async def validate_fix_suggestion(
    fix_suggestion: Dict[str, Any],
    project_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Validate a fix before suggesting it
    
    Args:
        fix_suggestion: Fix details including type, changes, and description
        project_context: Additional project context
    
    Returns:
        Validation result with warnings and recommendations
    """
    validation_result = {
        "is_valid": True,
        "warnings": [],
        "recommendations": [],
        "risk_level": "low",
        "estimated_time": "5-10 minutes",
        "requires_review": False
    }
    
    # Extract fix details
    fix_type = fix_suggestion.get("type", "unknown")
    changes = fix_suggestion.get("changes", {})
    description = fix_suggestion.get("description", "")
    
    # Validate based on fix type
    if fix_type == "dependency":
        # Check for major version changes
        for change in changes.values():
            if "major version" in str(change).lower():
                validation_result["warnings"].append(
                    "Major version upgrade detected - may introduce breaking changes"
                )
                validation_result["risk_level"] = "medium"
                validation_result["requires_review"] = True
        
        validation_result["recommendations"].append(
            "Run tests after applying dependency changes"
        )
        validation_result["estimated_time"] = "10-20 minutes"
    
    elif fix_type == "config":
        # Check for sensitive configuration changes
        sensitive_patterns = ["password", "token", "secret", "key", "credential"]
        for file, content in changes.items():
            if any(pattern in str(content).lower() for pattern in sensitive_patterns):
                validation_result["warnings"].append(
                    f"Sensitive configuration detected in {file}"
                )
                validation_result["risk_level"] = "high"
                validation_result["requires_review"] = True
        
        validation_result["recommendations"].append(
            "Use environment variables for sensitive values"
        )
    
    elif fix_type == "code":
        # Check for risky code patterns
        risky_patterns = ["exec", "eval", "subprocess", "os.system"]
        for file, content in changes.items():
            if any(pattern in str(content) for pattern in risky_patterns):
                validation_result["warnings"].append(
                    f"Potentially risky code pattern in {file}"
                )
                validation_result["risk_level"] = "medium"
        
        validation_result["estimated_time"] = "15-30 minutes"
    
    elif fix_type == "infrastructure":
        validation_result["warnings"].append(
            "Infrastructure changes may affect other services"
        )
        validation_result["risk_level"] = "medium"
        validation_result["requires_review"] = True
        validation_result["estimated_time"] = "20-40 minutes"
    
    # Add general recommendations
    if not validation_result["warnings"]:
        validation_result["recommendations"].append(
            "Fix appears safe to apply"
        )
    
    # Check if fix has been tried before
    if project_context:
        applied_fixes = project_context.get("applied_fixes", [])
        for applied in applied_fixes:
            if applied.get("description") == description:
                validation_result["warnings"].append(
                    "This fix has been tried before in this session"
                )
                validation_result["is_valid"] = False
    
    return validation_result