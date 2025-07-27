import os
from typing import Dict, Any, List, Optional
import httpx
from strands import tool
from loguru import logger
import json

# GitLab configuration
GITLAB_URL = os.getenv("GITLAB_URL", "http://gitlab:80")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")

# HTTP client for GitLab API
async def get_gitlab_client():
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN} if GITLAB_TOKEN else {}
    return httpx.AsyncClient(base_url=f"{GITLAB_URL}/api/v4", headers=headers, timeout=30.0)

def get_current_session_state():
    """Get session state from the current agent"""
    try:
        from strands import Agent
        # This is a workaround - in production, use proper context passing
        # For now, return empty dict to avoid errors
        return {}
    except:
        return {}

@tool
async def get_pipeline_details(pipeline_id: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get detailed information about a GitLab pipeline
    
    Args:
        pipeline_id: The pipeline ID
        project_id: The project ID (if not provided, will try to get from context)
    
    Returns:
        Pipeline details including status, stages, and duration
    """
    if not project_id:
        # Try to get from agent's session state
        try:
            from strands import Agent
            # Access the current agent instance if available
            current_agent = getattr(Agent, '_current_instance', None)
            if current_agent and hasattr(current_agent, 'session_state'):
                project_id = current_agent.session_state.get("project_id")
        except:
            pass
    
    if not project_id:
        return {"error": "Project ID not found in context"}
    
    async with await get_gitlab_client() as client:
        try:
            response = await client.get(f"/projects/{project_id}/pipelines/{pipeline_id}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get pipeline details: {e}")
            return {"error": str(e)}

@tool
async def get_pipeline_jobs(pipeline_id: str, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get all jobs in a pipeline with their status
    
    Args:
        pipeline_id: The pipeline ID
        project_id: The project ID (if not provided, will try to get from context)
    
    Returns:
        List of jobs with their status, stage, and timing information
    """
    if not project_id:
        session_state = get_current_session_state()
        project_id = session_state.get("project_id")
    
    if not project_id:
        return [{"error": "Project ID not found in context"}]
    
    async with await get_gitlab_client() as client:
        try:
            response = await client.get(f"/projects/{project_id}/pipelines/{pipeline_id}/jobs")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get pipeline jobs: {e}")
            return [{"error": str(e)}]

@tool
async def get_job_logs(job_id: str, project_id: Optional[str] = None) -> str:
    """Get logs for a specific pipeline job
    
    Args:
        job_id: The job ID
        project_id: The project ID (if not provided, will try to get from context)
    
    Returns:
        The job log content as text
    """
    if not project_id:
        session_state = get_current_session_state()
        project_id = session_state.get("project_id")
    
    if not project_id:
        return "Error: Project ID not found in context"
    
    async with await get_gitlab_client() as client:
        try:
            response = await client.get(f"/projects/{project_id}/jobs/{job_id}/trace")
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Failed to get job logs: {e}")
            return f"Error: {str(e)}"

@tool
async def get_file_content(file_path: str, ref: str = "HEAD", project_id: Optional[str] = None) -> str:
    """Get content of a file from GitLab repository
    
    Args:
        file_path: Path to the file in the repository
        ref: Git reference (branch, tag, or commit SHA)
        project_id: The project ID (if not provided, will try to get from context)
    
    Returns:
        The file content
    """
    if not project_id:
        session_state = get_current_session_state()
        project_id = session_state.get("project_id")
    
    if not project_id:
        return "Error: Project ID not found in context"
    
    async with await get_gitlab_client() as client:
        try:
            # URL encode the file path
            encoded_path = file_path.replace("/", "%2F")
            response = await client.get(
                f"/projects/{project_id}/repository/files/{encoded_path}/raw",
                params={"ref": ref}
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"Failed to get file content: {e}")
            return f"Error: {str(e)}"

@tool
async def get_recent_commits(limit: int = 10, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get recent commits for a project
    
    Args:
        limit: Number of commits to retrieve
        project_id: The project ID (if not provided, will try to get from context)
    
    Returns:
        List of recent commits with details
    """
    if not project_id:
        session_state = get_current_session_state()
        project_id = session_state.get("project_id")
    
    if not project_id:
        return [{"error": "Project ID not found in context"}]
    
    async with await get_gitlab_client() as client:
        try:
            response = await client.get(
                f"/projects/{project_id}/repository/commits",
                params={"per_page": limit}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get commits: {e}")
            return [{"error": str(e)}]

@tool
async def create_merge_request(
    title: str,
    description: str,
    changes: Dict[str, str],
    source_branch: Optional[str] = None,
    target_branch: str = "main",
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a merge request with fixes
    
    Args:
        title: MR title
        description: MR description
        changes: Dictionary of file paths to new content
        source_branch: Source branch name (auto-generated if not provided)
        target_branch: Target branch (default: main)
        project_id: The project ID (if not provided, will try to get from context)
    
    Returns:
        Created merge request details
    """
    if not project_id:
        session_state = get_current_session_state()
        project_id = session_state.get("project_id")
    
    if not project_id:
        return {"error": "Project ID not found in context"}
    
    # Generate branch name if not provided
    if not source_branch:
        import time
        source_branch = f"fix/pipeline-{int(time.time())}"
    
    async with await get_gitlab_client() as client:
        try:
            # Create branch
            await client.post(
                f"/projects/{project_id}/repository/branches",
                json={"branch": source_branch, "ref": target_branch}
            )
            
            # Create commits with changes
            actions = []
            for file_path, content in changes.items():
                actions.append({
                    "action": "update",
                    "file_path": file_path,
                    "content": content
                })
            
            await client.post(
                f"/projects/{project_id}/repository/commits",
                json={
                    "branch": source_branch,
                    "commit_message": f"Fix: {title}",
                    "actions": actions
                }
            )
            
            # Create merge request
            response = await client.post(
                f"/projects/{project_id}/merge_requests",
                json={
                    "source_branch": source_branch,
                    "target_branch": target_branch,
                    "title": title,
                    "description": description,
                    "remove_source_branch": True
                }
            )
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            logger.error(f"Failed to create merge request: {e}")
            return {"error": str(e)}

@tool
async def add_pipeline_comment(pipeline_id: str, comment: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Add a comment to a pipeline
    
    Args:
        pipeline_id: The pipeline ID
        comment: Comment text
        project_id: The project ID (if not provided, will try to get from context)
    
    Returns:
        Comment creation result
    """
    if not project_id:
        session_state = get_current_session_state()
        project_id = session_state.get("project_id")
    
    if not project_id:
        return {"error": "Project ID not found in context"}
    
    # GitLab doesn't have direct pipeline comments, so we'll add a note to the commit
    async with await get_gitlab_client() as client:
        try:
            # Get pipeline details first
            pipeline_response = await client.get(f"/projects/{project_id}/pipelines/{pipeline_id}")
            pipeline_response.raise_for_status()
            pipeline = pipeline_response.json()
            
            # Add note to the commit
            response = await client.post(
                f"/projects/{project_id}/repository/commits/{pipeline['sha']}/comments",
                json={"note": comment}
            )
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            logger.error(f"Failed to add comment: {e}")
            return {"error": str(e)}

@tool
async def get_project_by_name(project_name: str) -> Optional[Dict[str, Any]]:
    """Get GitLab project by name
    
    Args:
        project_name: Project name to search for
    
    Returns:
        Project details including ID
    """
    async with await get_gitlab_client() as client:
        try:
            # Search for project by name
            response = await client.get(
                "/projects",
                params={"search": project_name, "simple": True}
            )
            response.raise_for_status()
            
            projects = response.json()
            # Find exact match
            for project in projects:
                if project.get("name") == project_name:
                    return {
                        "id": str(project["id"]),
                        "name": project["name"],
                        "path_with_namespace": project.get("path_with_namespace")
                    }
            
            return None
        except Exception as e:
            logger.error(f"Failed to get project by name: {e}")
            return None