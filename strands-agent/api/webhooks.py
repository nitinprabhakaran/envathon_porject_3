"""Internal webhook processing functions for strands-agent
Note: All webhook endpoints are now in webhook-handler.
This file contains internal processing functions used by the queue processor.
"""
from typing import Dict, Any, Optional
import uuid
import asyncio
from datetime import datetime
from utils.logger import log
from config import settings
from db.session_manager import SessionManager
from agents.pipeline_agent import PipelineAgent
from agents.quality_agent import QualityAgent

# Import local branch naming utilities
from utils.branch_naming import (
    safe_extract_session_id, 
    is_fix_branch, 
    extract_branch_info,
    extract_session_id_from_branch
)

# Import fix iteration handler
from services.fix_iteration_handler import FixIterationHandler

# Import fix iteration handler
from services.fix_iteration_handler import FixIterationHandler

# Initialize components for internal processing
session_manager = SessionManager()
pipeline_agent = PipelineAgent()
quality_agent = QualityAgent()
fix_iteration_handler = FixIterationHandler()
fix_iteration_handler = FixIterationHandler()

async def handle_pipeline_success(project_id: str, ref: str):
    """Handle successful pipeline runs"""
    log.info(f"handle_pipeline_success called: project={project_id}, ref={ref}")
    sessions = await session_manager.get_active_sessions()
    log.info(f"Found {len(sessions)} active sessions")
    
    # Check if this is a fix branch that succeeded
    if is_fix_branch(ref):
        log.info(f"Processing success for fix branch: {ref}")
        
        # Extract session ID from branch name using new utilities
        session_id = safe_extract_session_id(ref)
        if not session_id:
            log.warning(f"Could not extract session ID from fix branch: {ref}")
            return {"status": "error", "reason": "Invalid fix branch format"}
        
        # Find the specific session
        target_session = None
        for session in sessions:
            if session.get("id") == session_id and session.get("project_id") == project_id:
                target_session = session
                break
        
        if target_session:
            log.info(f"Found matching session {session_id} for branch {ref}")
            
            # Use fix iteration handler for success
            try:
                result = await fix_iteration_handler.handle_fix_branch_success(
                    session_id, ref, None, {}  # We don't have full webhook data here
                )
                log.info(f"Fix iteration handler result: {result}")
                return {"status": "updated", "action": "fix_succeeded"}
            except Exception as e:
                log.error(f"Error in fix iteration handler for success: {e}")
                
                # Fallback to old logic
                fix_attempts = await session_manager.get_fix_attempts(session_id)
                for attempt in fix_attempts:
                    stored_branch = attempt.get('branch_name', '').strip()
                    if stored_branch == ref.strip() and attempt["status"] == "pending":
                        await session_manager.update_fix_attempt(
                            session_id, attempt["attempt_number"], "success"
                        )
                        return {"status": "updated", "action": "fix_succeeded"}
        else:
            log.warning(f"No matching session found for branch {ref} with project {project_id}")
    
    # Check if this is target branch after merge
    else:
        for session in sessions:
            if (session.get("project_id") == project_id and 
                session.get("merge_request_url") and
                session.get("status") == "active"):
                
                # Check if branch matches the session's target branch
                target_branch = session.get("branch", "main")
                if ref == target_branch:
                    # Check if any fix attempt was recently successful
                    fix_attempts = await session_manager.get_fix_attempts(session["id"])
                    for attempt in fix_attempts:
                        if attempt["status"] == "success":
                            await session_manager.mark_session_resolved(session["id"])
                            await session_manager.add_message(
                                session["id"],
                                "assistant",
                                f"✅ **Issue Fully Resolved!**\n\n"
                                f"The fix has been merged and the pipeline on `{ref}` branch is passing.\n"
                                f"The issue has been successfully resolved."
                            )
                            log.info(f"Marked session {session['id']} as resolved - target branch succeeded after merge")
                            return {"status": "resolved", "action": "target_branch_success"}
    
    return {"status": "ignored", "reason": "No matching session found"}


async def handle_pipeline_failure(project_id: str, ref: str, webhook_data: Dict[str, Any]):
    """Handle failed pipeline runs - especially for fix branches"""
    log.info(f"handle_pipeline_failure called: project={project_id}, ref={ref}")
    
    # Check if this is a fix branch that failed
    if is_fix_branch(ref):
        log.info(f"Processing failure for fix branch: {ref}")
        
        # Extract session ID from branch name
        session_id = safe_extract_session_id(ref)
        if not session_id:
            log.warning(f"Could not extract session ID from fix branch: {ref}")
            return {"status": "error", "reason": "Invalid fix branch format"}
        
        # Check if session exists
        session = await session_manager.get_session(session_id)
        if not session or session.get("project_id") != project_id:
            log.warning(f"No matching session found for fix branch: {ref}")
            return {"status": "error", "reason": "Session not found"}
        
        # Use fix iteration handler for failure
        try:
            pipeline_id = webhook_data.get("object_attributes", {}).get("id")
            result = await fix_iteration_handler.handle_fix_branch_failure(
                session_id, ref, str(pipeline_id), webhook_data
            )
            log.info(f"Fix iteration handler result: {result}")
            
            if result.get("status") == "iteration_triggered":
                return {"status": "iteration_triggered", "attempt_number": result.get("attempt_number")}
            elif result.get("status") == "max_attempts_reached":
                return {"status": "max_attempts_reached"}
            else:
                return {"status": "handled"}
                
        except Exception as e:
            log.error(f"Error in fix iteration handler for failure: {e}")
            return {"status": "error", "reason": str(e)}
    
    return {"status": "ignored", "reason": "Not a fix branch"}


# Remove old branch parsing functions - replaced by branch_naming utilities

async def analyze_pipeline_failure(session_id: str, project_id: str, pipeline_id: str, webhook_data: Dict):
    """Background task to analyze pipeline failure"""
    try:
        log.info(f"Starting pipeline analysis for session {session_id}")
        
        # Run analysis with webhook_data first, session_id second
        analysis = await pipeline_agent.analyze_failure(
            webhook_data, session_id
        )
        
        # Extract text if analysis is a complex object
        if isinstance(analysis, dict) and "content" in analysis:
            content = analysis["content"]
            if isinstance(content, list) and len(content) > 0:
                analysis = content[0].get("text", str(analysis))
        
        # Store analysis in conversation
        await session_manager.add_message(session_id, "assistant", analysis)
        
        log.info(f"Pipeline analysis complete for session {session_id}")
        
    except Exception as e:
        error_msg = str(e)
        # Handle EventLoopException which contains curly braces
        if "EventLoopException" in type(e).__name__:
            error_msg = error_msg.replace("{", "{{").replace("}", "}}")
        
        log.error(f"Pipeline/Quality analysis failed: {error_msg}", exc_info=True)
        
        # Check if it's a token limit error
        if "prompt is too long" in error_msg:
            await session_manager.add_message(
                session_id,
                "assistant",
                "Analysis failed: The pipeline logs are too large to analyze. This typically happens with verbose test output or coverage reports. Please check the GitLab UI directly for the full logs, or consider reducing log verbosity in your CI configuration."
            )
        else:
            await session_manager.add_message(
                session_id,
                "assistant",
                f"Analysis failed: {error_msg}"
            )

async def analyze_quality_from_pipeline(session_id: str, project_key: str, gitlab_project_id: str, webhook_data: Dict):
    """Analyze quality issues when detected from pipeline failure"""
    try:
        log.info(f"Starting quality analysis from pipeline failure for session {session_id}")
        
        # First, try to get actual quality data from SonarQube
        from tools.sonarqube import get_project_issues, get_project_metrics, get_project_quality_gate_status
        
        # Get quality gate status
        quality_status = await get_project_quality_gate_status(project_key)
        
        # Check if there are actual quality issues or just no analysis
        project_status = quality_status.get("projectStatus", {})
        if project_status.get("status") == "NONE" or not project_status:
            log.warning(f"No quality gate configured or no analysis for {project_key}")
            
            # This is not a quality issue - it's a configuration/analysis issue
            # Update to pipeline failure
            await session_manager.update_session_metadata(
                session_id,
                {"session_type": "pipeline"}
            )
            
            await session_manager.add_message(
                session_id,
                "assistant",
                f"## ⚠️ SonarQube Analysis Issue\n\n"
                f"The pipeline failed at the SonarQube check stage, but this is not due to quality gate failure.\n\n"
                f"**Issue**: No SonarQube analysis results found for project '{project_key}'\n\n"
                f"**Possible reasons:**\n"
                f"1. SonarQube analysis was not performed\n"
                f"2. Project key mismatch between CI configuration and SonarQube\n"
                f"3. Authentication/permission issues\n"
                f"4. SonarQube server connectivity problems\n\n"
                f"**Recommended actions:**\n"
                f"1. Check the sonarqube-check job logs for specific errors\n"
                f"2. Verify the project key in your `sonar-project.properties` or CI configuration\n"
                f"3. Ensure SonarQube authentication token is valid\n"
                f"4. Verify the project exists in SonarQube\n\n"
                f"This appears to be a **pipeline configuration issue**, not a code quality issue."
            )
            return
        
        # Get issue counts by type
        bugs = await get_project_issues(project_key, types="BUG", limit=500)
        vulnerabilities = await get_project_issues(project_key, types="VULNERABILITY", limit=500)
        code_smells = await get_project_issues(project_key, types="CODE_SMELL", limit=500)
        
        # Get project metrics
        try:
            metrics = await get_project_metrics(project_key)
        except Exception as e:
            log.warning(f"Could not fetch metrics for {project_key}: {e}")
            metrics = {}
        
        # Calculate counts
        total_issues = len(bugs) + len(vulnerabilities) + len(code_smells)
        critical_count = sum(1 for b in bugs if b.get("severity") in ["CRITICAL", "BLOCKER"])
        critical_count += sum(1 for v in vulnerabilities if v.get("severity") in ["CRITICAL", "BLOCKER"])
        major_count = sum(1 for b in bugs if b.get("severity") == "MAJOR")
        major_count += sum(1 for v in vulnerabilities if v.get("severity") == "MAJOR")
        
        # Update session with quality metrics
        await session_manager.update_quality_metrics(
            session_id,
            {
                "total_issues": total_issues,
                "bug_count": len(bugs),
                "vulnerability_count": len(vulnerabilities),
                "code_smell_count": len(code_smells),
                "critical_issues": critical_count,
                "major_issues": major_count,
                "coverage": metrics.get("coverage", "0"),
                "duplicated_lines_density": metrics.get("duplicated_lines_density", "0"),
                "reliability_rating": metrics.get("reliability_rating", "E"),
                "security_rating": metrics.get("security_rating", "E"),
                "maintainability_rating": metrics.get("maintainability_rating", "E")
            }
        )
        
        # Prepare enhanced webhook data with quality information
        enhanced_webhook_data = {
            **webhook_data,
            "qualityGate": project_status
        }
        
        # Run quality analysis with working version signature: analyze_quality_issues(session_id, project_key, gitlab_project_id, webhook_data)
        analysis = await quality_agent.analyze_quality_issues(
            session_id, project_key, gitlab_project_id, enhanced_webhook_data
        )
        
        # Extract text if analysis is a complex object
        if isinstance(analysis, dict) and "content" in analysis:
            content = analysis["content"]
            if isinstance(content, list) and len(content) > 0:
                analysis = content[0].get("text", str(analysis))
        
        # Store analysis in conversation
        await session_manager.add_message(session_id, "assistant", analysis)
        
        log.info(f"Quality analysis complete for session {session_id}")
        
    except Exception as e:
        log.error(f"Quality analysis failed: {e}", exc_info=True)
        await session_manager.add_message(
            session_id,
            "assistant",
            f"Quality analysis failed: {str(e)}"
        )

async def analyze_quality_issues(session_id: str, project_key: str, gitlab_project_id: str, webhook_data: Dict):
    """Background task to analyze quality issues"""
    try:
        log.info(f"Starting quality analysis for session {session_id}")
        
        # First, fetch actual metrics from SonarQube
        from tools.sonarqube import get_project_issues, get_project_metrics
        
        # Get issue counts by type
        bugs = await get_project_issues(project_key, types="BUG", limit=500)
        vulnerabilities = await get_project_issues(project_key, types="VULNERABILITY", limit=500)
        code_smells = await get_project_issues(project_key, types="CODE_SMELL", limit=500)
        
        # Get project metrics
        try:
            metrics = await get_project_metrics(project_key)
        except Exception as e:
            log.warning(f"Could not fetch metrics for {project_key}: {e}")
            metrics = {}
        
        # Calculate counts
        total_issues = len(bugs) + len(vulnerabilities) + len(code_smells)
        critical_count = sum(1 for b in bugs if b.get("severity") in ["CRITICAL", "BLOCKER"])
        critical_count += sum(1 for v in vulnerabilities if v.get("severity") in ["CRITICAL", "BLOCKER"])
        major_count = sum(1 for b in bugs if b.get("severity") == "MAJOR")
        major_count += sum(1 for v in vulnerabilities if v.get("severity") == "MAJOR")
        
        # Update session with quality metrics
        await session_manager.update_quality_metrics(
            session_id,
            {
                "total_issues": total_issues,
                "bug_count": len(bugs),
                "vulnerability_count": len(vulnerabilities),
                "code_smell_count": len(code_smells),
                "critical_issues": critical_count,
                "major_issues": major_count,
                "coverage": metrics.get("coverage", "0"),
                "duplicated_lines_density": metrics.get("duplicated_lines_density", "0"),
                "reliability_rating": metrics.get("reliability_rating", "E"),
                "security_rating": metrics.get("security_rating", "E"),
                "maintainability_rating": metrics.get("maintainability_rating", "E")
            }
        )
        
        # Run analysis with working version signature: analyze_quality_issues(session_id, project_key, gitlab_project_id, webhook_data)
        analysis = await quality_agent.analyze_quality_issues(
            session_id, project_key, gitlab_project_id, webhook_data
        )
        
        # Extract text if analysis is a complex object
        if isinstance(analysis, dict) and "content" in analysis:
            content = analysis["content"]
            if isinstance(content, list) and len(content) > 0:
                analysis = content[0].get("text", str(analysis))
        
        # Store analysis in conversation
        await session_manager.add_message(session_id, "assistant", analysis)
        
        log.info(f"Quality analysis complete for session {session_id}")
        
    except Exception as e:
        error_msg = str(e)
        if "{" in error_msg or "}" in error_msg:
            error_msg = error_msg.replace("{", "{{").replace("}", "}}")

        log.error(f"Quality analysis failed: {e}", exc_info=True)
        await session_manager.add_message(
            session_id,
            "assistant",
            f"Analysis failed: {str(e)}"
        )

async def get_gitlab_project_id(sonarqube_key: str) -> Optional[str]:
    """Map SonarQube project key to GitLab project ID"""
    from tools.gitlab import get_gitlab_client
    
    log.info(f"Looking up GitLab project for SonarQube key: {sonarqube_key}")
    
    async with await get_gitlab_client() as client:
        try:
            # Strategy 1: Direct lookup by path (most common case)
            if "/" in sonarqube_key:
                encoded_path = sonarqube_key.replace("/", "%2F")
                try:
                    response = await client.get(f"/projects/{encoded_path}")
                    if response.status_code == 200:
                        project_id = str(response.json().get("id"))
                        log.info(f"Found project by path: {sonarqube_key} -> {project_id}")
                        return project_id
                except:
                    pass
            
            # Strategy 2: Search by name (if key is just project name)
            search_params = {"search": sonarqube_key, "simple": "true"}
            response = await client.get("/projects", params=search_params)
            
            if response.status_code == 200:
                projects = response.json()
                
                # Try exact name match first
                for project in projects:
                    if project.get("name") == sonarqube_key:
                        project_id = str(project.get("id"))
                        log.info(f"Found project by exact name match: {sonarqube_key} -> {project_id}")
                        return project_id
                
                # Try path_with_namespace match
                for project in projects:
                    if project.get("path_with_namespace", "").endswith(f"/{sonarqube_key}"):
                        project_id = str(project.get("id"))
                        log.info(f"Found project by path suffix: {sonarqube_key} -> {project_id}")
                        return project_id
                
                # If only one result, use it
                if len(projects) == 1:
                    project_id = str(projects[0].get("id"))
                    log.info(f"Found single project match: {sonarqube_key} -> {project_id}")
                    return project_id
            
            # Strategy 3: If key contains underscore, try without group prefix
            if "_" in sonarqube_key:
                parts = sonarqube_key.split("_", 1)
                if len(parts) == 2:
                    group_name, project_name = parts
                    
                    # Search in specific group
                    group_response = await client.get(f"/groups", params={"search": group_name})
                    if group_response.status_code == 200:
                        groups = group_response.json()
                        for group in groups:
                            if group.get("name").lower() == group_name.lower():
                                group_id = group.get("id")
                                
                                # Get projects in this group
                                projects_response = await client.get(
                                    f"/groups/{group_id}/projects",
                                    params={"search": project_name}
                                )
                                if projects_response.status_code == 200:
                                    group_projects = projects_response.json()
                                    for project in group_projects:
                                        if project.get("name") == project_name:
                                            project_id = str(project.get("id"))
                                            log.info(f"Found project in group: {sonarqube_key} -> {project_id}")
                                            return project_id
            
            log.error(f"Could not find GitLab project for SonarQube key: {sonarqube_key}")
            return None
            
        except Exception as e:
            log.error(f"Error looking up GitLab project: {e}")
            return None

