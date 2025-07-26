from strands_agents import tool
from typing import Dict, Any, List, Optional
import hashlib
import json, yaml, re
from datetime import datetime
from db.session_manager import SessionManager
from vector.qdrant_client import QdrantManager

# These will be injected from the agent context
def get_context(name: str):
    """Helper to get context from agent"""
    from strands_agents import get_current_agent
    agent = get_current_agent()
    return agent.context.get(name)

@tool
async def analyze_pipeline_logs(pipeline_id: str, job_name: Optional[str] = None) -> Dict[str, Any]:
    """Analyze pipeline logs to extract error patterns and root causes"""
    mcp_manager = get_context("mcp_manager")
    project_id = get_context("project_id")
    
    # Get pipeline details via GitLab MCP
    pipeline_details = await mcp_manager.gitlab_call(
        "get_pipeline_details",
        {"project_id": project_id, "pipeline_id": pipeline_id}
    )
    
    # Get failed jobs
    jobs = await mcp_manager.gitlab_call(
        "get_pipeline_jobs",
        {"project_id": project_id, "pipeline_id": pipeline_id}
    )
    
    failed_jobs = [job for job in jobs if job["status"] == "failed"]
    
    analysis = {
        "pipeline_id": pipeline_id,
        "failed_jobs": [],
        "error_patterns": [],
        "root_cause_candidates": []
    }
    
    for job in failed_jobs:
        if job_name and job["name"] != job_name:
            continue
            
        # Get job logs
        logs = await mcp_manager.gitlab_call(
            "get_job_logs",
            {"project_id": project_id, "job_id": job["id"]}
        )
        
        # Extract error patterns
        error_lines = [line for line in logs.split('\n') if any(
            keyword in line.lower() for keyword in ['error', 'failed', 'exception', 'fatal']
        )]
        
        analysis["failed_jobs"].append({
            "job_name": job["name"],
            "job_id": job["id"],
            "stage": job["stage"],
            "error_preview": error_lines[:5] if error_lines else ["No clear error found"]
        })
    
    return analysis

@tool
async def extract_error_signature(logs: str) -> str:
    """Extract a unique signature from error logs for similarity matching"""
    # Remove timestamps, IDs, and other variable content
    
    # Remove timestamps
    logs = re.sub(r'\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}', '', logs)
    # Remove UUIDs
    logs = re.sub(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', '', logs)
    # Remove hex strings
    logs = re.sub(r'0x[a-f0-9]+', '', logs)
    # Remove line numbers
    logs = re.sub(r'line \d+', 'line N', logs)
    # Remove file paths but keep file names
    logs = re.sub(r'[/\\][\w/\\]+\/([\w\.]+)', r'\1', logs)
    
    # Extract key error lines
    error_lines = []
    for line in logs.split('\n'):
        if any(keyword in line.lower() for keyword in ['error', 'exception', 'failed', 'fatal']):
            error_lines.append(line.strip())
    
    # Create signature
    signature_text = '\n'.join(error_lines[:10])  # Top 10 error lines
    signature_hash = hashlib.sha256(signature_text.encode()).hexdigest()[:16]
    
    return f"{signature_hash}:{signature_text[:200]}"

@tool
async def intelligent_log_truncation(logs: str, max_tokens: int = 4000) -> str:
    """Intelligently truncate logs while preserving error context"""
    lines = logs.split('\n')
    
    # Priority sections
    error_lines = []
    context_lines = []
    summary_lines = []
    
    for i, line in enumerate(lines):
        if any(keyword in line.lower() for keyword in ['error', 'failed', 'exception', 'fatal']):
            # Get error line plus context (5 lines before and after)
            start = max(0, i - 5)
            end = min(len(lines), i + 6)
            error_lines.extend(lines[start:end])
        elif any(keyword in line.lower() for keyword in ['summary', 'result', 'finished']):
            summary_lines.append(line)
    
    # Build truncated log
    truncated = []
    truncated.append("=== ERROR CONTEXT ===")
    truncated.extend(error_lines[:50])  # Max 50 error-related lines
    
    if summary_lines:
        truncated.append("\n=== SUMMARY ===")
        truncated.extend(summary_lines[:10])
    
    result = '\n'.join(truncated)
    
    # Further truncate if needed
    if len(result) > max_tokens * 4:  # Rough estimate: 4 chars per token
        result = result[:max_tokens * 4] + "\n... [truncated]"
    
    return result

@tool
async def get_session_context(session_id: str) -> Dict[str, Any]:
    """Get the full context of a session including conversation history"""
    
    session_manager = SessionManager()
    session = await session_manager.get_session(session_id)
    
    if not session:
        return {"error": "Session not found"}
    
    return {
        "session_id": session_id,
        "project_id": session["project_id"],
        "pipeline_id": session["pipeline_id"],
        "status": session["status"],
        "conversation_history": session["conversation_history"],
        "applied_fixes": session["applied_fixes"],
        "successful_fixes": session["successful_fixes"],
        "created_at": session["created_at"],
        "last_activity": session["last_activity"]
    }

@tool
async def update_session_state(
    session_id: str,
    update_type: str,
    data: Dict[str, Any]
) -> Dict[str, Any]:
    """Update session state with new information"""
    
    session_manager = SessionManager()
    
    if update_type == "applied_fix":
        await session_manager.add_applied_fix(session_id, data)
    elif update_type == "successful_fix":
        await session_manager.mark_fix_successful(session_id, data)
    elif update_type == "metadata":
        await session_manager.update_metadata(session_id, data)
    
    return {"status": "updated", "update_type": update_type}

@tool
async def get_relevant_code_context(
    error_signature: str,
    project_id: str,
    expand_scope: bool = False
) -> Dict[str, Any]:
    """Retrieve code sections most likely related to the error"""
    
    qdrant = QdrantManager()
    
    # Search for relevant code in project embeddings
    results = await qdrant.search_code_context(
        project_id=project_id,
        query=error_signature,
        limit=10 if expand_scope else 5
    )
    
    return {
        "relevant_files": [r["file_path"] for r in results],
        "code_sections": results,
        "confidence_scores": [r["score"] for r in results]
    }

@tool
async def request_additional_context(
    context_type: str,
    scope: str,
    specific_files: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Request additional context when current information is insufficient"""
    mcp_manager = get_context("mcp_manager")
    project_id = get_context("project_id")
    
    context_data = {
        "context_type": context_type,
        "scope": scope,
        "files_retrieved": []
    }
    
    if context_type == "dependencies":
        # Get package files
        files_to_check = ["package.json", "requirements.txt", "Gemfile", "go.mod", "pom.xml"]
        for file in files_to_check:
            try:
                content = await mcp_manager.gitlab_call(
                    "get_file_content",
                    {"project_id": project_id, "file_path": file, "ref": "HEAD"}
                )
                if content:
                    context_data["files_retrieved"].append({
                        "file": file,
                        "content": content
                    })
            except:
                continue
    
    elif context_type == "test_files":
        # Get test files related to failed areas
        # This would need more sophisticated logic in production
        pass
    
    elif context_type == "related_modules" and specific_files:
        for file_path in specific_files:
            try:
                content = await mcp_manager.gitlab_call(
                    "get_file_content",
                    {"project_id": project_id, "file_path": file_path, "ref": "HEAD"}
                )
                context_data["files_retrieved"].append({
                    "file": file_path,
                    "content": content
                })
            except:
                continue
    
    return context_data

@tool
async def get_shared_pipeline_context(
    project_id: str,
    template_ref: str
) -> Dict[str, Any]:
    """Retrieve shared pipeline templates and their context"""
    mcp_manager = get_context("mcp_manager")
    
    # Get main CI file
    ci_content = await mcp_manager.gitlab_call(
        "get_file_content",
        {"project_id": project_id, "file_path": ".gitlab-ci.yml", "ref": "HEAD"}
    )
    
    # Parse includes

    ci_config = yaml.safe_load(ci_content)
    includes = ci_config.get("include", [])
    
    shared_context = {
        "main_ci_file": ci_content,
        "includes": [],
        "variables": ci_config.get("variables", {})
    }
    
    # Fetch included templates
    for include in includes:
        if isinstance(include, dict) and "project" in include:
            template_content = await mcp_manager.gitlab_call(
                "get_file_content",
                {
                    "project_id": include["project"],
                    "file_path": include.get("file", ".gitlab-ci.yml"),
                    "ref": include.get("ref", "HEAD")
                }
            )
            shared_context["includes"].append({
                "source": include,
                "content": template_content
            })
    
    return shared_context

@tool
async def trace_pipeline_inheritance(ci_file_path: str = ".gitlab-ci.yml") -> Dict[str, Any]:
    """Follow include/extends chains to map full pipeline context"""
    mcp_manager = get_context("mcp_manager")
    project_id = get_context("project_id")
    
    # Get the CI file
    ci_content = await mcp_manager.gitlab_call(
        "get_file_content",
        {"project_id": project_id, "file_path": ci_file_path, "ref": "HEAD"}
    )
    
    ci_config = yaml.safe_load(ci_content)
    
    inheritance_map = {
        "base_file": ci_file_path,
        "includes": [],
        "extends_chain": {},
        "variables_chain": {}
    }
    
    # Process includes
    includes = ci_config.get("include", [])
    for include in includes:
        inheritance_map["includes"].append(include)
    
    # Process job extends
    for job_name, job_config in ci_config.items():
        if isinstance(job_config, dict) and "extends" in job_config:
            inheritance_map["extends_chain"][job_name] = job_config["extends"]
    
    return inheritance_map

@tool
async def get_cicd_variables(
    project_id: str,
    security_level: str = "pipeline"
) -> Dict[str, Any]:
    """Retrieve CI/CD variables based on security clearance"""
    mcp_manager = get_context("mcp_manager")
    
    variables = {
        "pipeline_level": {},
        "project_level": {},
        "masked_values": []
    }
    
    if security_level in ["pipeline", "project", "all"]:
        # Get project variables
        project_vars = await mcp_manager.gitlab_call(
            "get_project_variables",
            {"project_id": project_id}
        )
        
        for var in project_vars:
            if var.get("masked", False):
                variables["masked_values"].append(var["key"])
            else:
                variables["project_level"][var["key"]] = var["value"]
    
    return variables

@tool
async def search_similar_errors(
    error_signature: str,
    project_id: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Search for similar errors in historical data"""
    
    qdrant = QdrantManager()
    
    # Search in error patterns collection
    results = await qdrant.search_similar_errors(
        error_signature=error_signature,
        project_id=project_id,
        limit=limit
    )
    
    # Enrich with fix success rates
    enriched_results = []
    for result in results:
        enriched = {
            **result,
            "similarity_score": result["score"],
            "success_rate": result.get("payload", {}).get("success_rate", 0),
            "avg_fix_time": result.get("payload", {}).get("avg_fix_time", "unknown"),
            "fix_suggestions": result.get("payload", {}).get("fix_suggestions", [])
        }
        enriched_results.append(enriched)
    
    return enriched_results

@tool
async def store_successful_fix(
    session_id: str,
    fix_description: str,
    fix_type: str,
    confidence_score: float
) -> Dict[str, Any]:
    """Store a successful fix for future reference"""
    session_manager = SessionManager()
    qdrant = QdrantManager()
    
    # Get session details
    session = await session_manager.get_session(session_id)
    
    # Store in database
    fix_id = await session_manager.store_historical_fix(
        session_id=session_id,
        error_signature=session["error_signature"],
        fix_description=fix_description,
        fix_type=fix_type,
        confidence_score=confidence_score
    )
    
    # Update vector database
    await qdrant.store_successful_fix(
        error_signature=session["error_signature"],
        fix_description=fix_description,
        project_context={
            "project_id": session["project_id"],
            "fix_type": fix_type,
            "confidence": confidence_score
        }
    )
    
    return {
        "fix_id": fix_id,
        "status": "stored",
        "message": "Fix stored successfully for future reference"
    }

@tool
async def validate_fix_suggestion(
    fix_suggestion: Dict[str, Any],
    project_context: Dict[str, Any]
) -> Dict[str, Any]:
    """Validate a fix suggestion before applying"""
    mcp_manager = get_context("mcp_manager")
    project_id = get_context("project_id")
    
    validation_result = {
        "is_valid": True,
        "warnings": [],
        "quality_impact": {},
        "estimated_time": "5-10 minutes"
    }
    
    # Check with SonarQube if the fix might introduce issues
    if fix_suggestion.get("type") == "code_change":
        quality_status = await mcp_manager.sonar_call(
            "get_project_quality_status",
            {"project_key": project_id}
        )
        
        # Basic validation logic
        if quality_status.get("qualityGate", {}).get("status") == "ERROR":
            validation_result["warnings"].append(
                "Project already has quality gate failures. Fix might not address root cause."
            )
    
    return validation_result