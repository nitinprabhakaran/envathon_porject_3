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

# Initialize components for internal processing
session_manager = SessionManager()
pipeline_agent = PipelineAgent()
quality_agent = QualityAgent()

# Internal processing functions - no webhook endpoints
# All webhook endpoints are now in webhook-handler

# Session creation functions moved to webhook-handler
# These functions are now called by the queue processor when processing events

async def handle_pipeline_success(project_id: str, ref: str):
    """Handle successful pipeline runs"""
    log.info(f"handle_pipeline_success called: project={project_id}, ref={ref}")
    sessions = await session_manager.get_active_sessions()
    log.info(f"Found {len(sessions)} active sessions")
    
    # Check if this is a fix branch that succeeded
    if ref and ref.startswith("fix/"):
        log.info(f"Processing success for fix branch: {ref}")
        for session in sessions:
            if session.get("project_id") == project_id and session.get("status") == "active":
                log.info(f"Checking session {session['id']} for fix attempts")
                # Check fix attempts for THIS EXACT branch
                fix_attempts = await session_manager.get_fix_attempts(session["id"])
                log.info(f"Found {len(fix_attempts)} fix attempts for session {session['id']}")
                for attempt in fix_attempts:
                    # Clean both branch names before comparison
                    stored_branch = attempt.get('branch_name', '').strip()
                    incoming_branch = ref.strip()
                    
                    log.info(f"Comparing branches - stored: '{stored_branch}', incoming: '{incoming_branch}'")
                    
                    if stored_branch == incoming_branch and attempt["status"] == "pending":
                        # This is OUR fix branch that succeeded
                        await session_manager.update_fix_attempt(
                            session["id"],
                            attempt["attempt_number"],
                            "success"
                        )
                        
                        # Update webhook_data for UI
                        webhook_data = session.get("webhook_data", {})
                        fix_attempts_data = webhook_data.get("fix_attempts", [])
                        
                        # Update the status in webhook_data
                        for fa in fix_attempts_data:
                            if fa.get("branch", "").strip() == incoming_branch:
                                fa["status"] = "success"
                                fa["succeeded_at"] = datetime.utcnow().isoformat()
                                break
                        
                        webhook_data["fix_attempts"] = fix_attempts_data
                        await session_manager.update_session_metadata(session["id"], {"webhook_data": webhook_data})
                        
                        # Add success message with pipeline URL
                        pipeline_url = f"{settings.gitlab_url}/{session.get('project_name')}/-/pipelines"
                        await session_manager.add_message(
                            session["id"],
                            "assistant",
                            f"✅ **Fix Successful!**\n\n"
                            f"The pipeline on branch `{ref}` has passed all checks.\n\n"
                            f"**Next Steps:**\n"
                            f"1. Review the changes in the merge request\n"
                            f"2. Merge when ready: {attempt.get('merge_request_url')}\n"
                            f"3. The fix will be applied to the target branch after merge\n\n"
                            f"[View Pipeline]({pipeline_url})"
                        )
                        
                        log.info(f"Marked fix attempt as successful for session {session['id']}")
                        return {"status": "updated", "action": "fix_succeeded"}
    
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
    
# Session creation and webhook endpoint logic moved to webhook-handler
# This file now only contains analysis functions called by queue processor

# SonarQube webhook endpoint removed - all webhooks now go through webhook-handler
# Quality gate failures are detected from GitLab pipeline logs and routed intelligently

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

