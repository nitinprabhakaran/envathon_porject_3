"""GitLab tools for CI/CD failure analysis"""
import httpx
from typing import Dict, Any, List, Optional
from strands import tool
from datetime import datetime
from utils.logger import log
from config import settings
from urllib.parse import quote

async def get_gitlab_client():
    """Create GitLab API client"""
    headers = {"PRIVATE-TOKEN": settings.gitlab_token} if settings.gitlab_token else {}
    return httpx.AsyncClient(
        base_url=f"{settings.gitlab_url}/api/v4", 
        headers=headers, 
        timeout=30.0
    )

def truncate_log(log_content: str, max_size: int = settings.max_log_size) -> str:
    """Truncate log content if too large, keeping beginning and end"""
    if len(log_content) <= max_size:
        return log_content
    
    # Keep first 40% and last 40% of allowed size
    start_size = int(max_size * 0.4)
    end_size = int(max_size * 0.4)
    
    truncated = (
        log_content[:start_size] + 
        f"\n\n... [TRUNCATED - Log too large, showing first {start_size} and last {end_size} characters] ...\n\n" + 
        log_content[-end_size:]
    )
    
    return truncated

@tool
async def get_pipeline_jobs(pipeline_id: str, project_id: str) -> List[Dict[str, Any]]:
    """Get all jobs in a pipeline with their status
    
    Args:
        pipeline_id: GitLab pipeline ID
        project_id: GitLab project ID
    
    Returns:
        List of jobs with status, stage, and timing information
    """
    log.info(f"Getting jobs for pipeline {pipeline_id} in project {project_id}")
    
    async with await get_gitlab_client() as client:
        try:
            response = await client.get(f"/projects/{project_id}/pipelines/{pipeline_id}/jobs")
            response.raise_for_status()
            jobs = response.json()
            log.debug(f"Found {len(jobs)} jobs in pipeline")
            return jobs
        except Exception as e:
            log.error(f"Failed to get pipeline jobs: {e}")
            return [{"error": str(e)}]

@tool
async def get_job_logs(job_id: str, project_id: str, max_size: Optional[int] = None) -> str:
    """Get logs for a specific pipeline job
    
    Args:
        job_id: GitLab job ID
        project_id: GitLab project ID
        max_size: Maximum log size in characters (default: 50000)
    
    Returns:
        Job log content as text (truncated if too large)
    """
    log.info(f"Getting logs for job {job_id} in project {project_id}")
    
    if max_size is None:
        max_size = settings.max_log_size
    
    async with await get_gitlab_client() as client:
        try:
            response = await client.get(f"/projects/{project_id}/jobs/{job_id}/trace")
            response.raise_for_status()
            
            log_content = response.text
            original_size = len(log_content)
            
            # Truncate if too large
            if original_size > max_size:
                log.warning(f"Log size ({original_size} chars) exceeds limit ({max_size} chars), truncating...")
                log_content = truncate_log(log_content, max_size)
            
            return log_content
            
        except Exception as e:
            log.error(f"Failed to get job logs: {e}")
            return f"Error getting job logs: {str(e)}"

@tool
async def get_file_content(file_path: str, project_id: str, ref: str = "HEAD") -> str:
    """Get content of a file from GitLab repository
    
    Args:
        file_path: Path to file in repository
        project_id: GitLab project ID
        ref: Git reference (branch, tag, or commit SHA)
    
    Returns:
        File content as text
    """
    log.info(f"Getting file {file_path} from project {project_id} at ref {ref}")
    
    async with await get_gitlab_client() as client:
        try:
            encoded_path = quote(file_path, safe='')
            response = await client.get(
                f"/projects/{project_id}/repository/files/{encoded_path}/raw",
                params={"ref": ref}
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            log.error(f"Failed to get file content: {e}")
            return f"Error getting file content: {str(e)}"

@tool
async def get_recent_commits(project_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent commits for a project
    
    Args:
        project_id: GitLab project ID
        limit: Number of commits to retrieve
    
    Returns:
        List of recent commits
    """
    log.info(f"Getting {limit} recent commits for project {project_id}")
    
    async with await get_gitlab_client() as client:
        try:
            response = await client.get(
                f"/projects/{project_id}/repository/commits",
                params={"per_page": limit}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error(f"Failed to get commits: {e}")
            return [{"error": str(e)}]

@tool
async def create_merge_request(
    title: str,
    description: str,
    files: Dict[str, str],
    project_id: str,
    source_branch: str,
    target_branch: str = "main"
) -> Dict[str, Any]:
    """Create a merge request with file changes
    
    Args:
        title: MR title
        description: MR description
        files: Dictionary of file paths to new content
        project_id: GitLab project ID
        source_branch: Source branch name
        target_branch: Target branch name
    
    Returns:
        Created merge request details
    """
    log.info(f"Creating MR '{title}' in project {project_id}")
    
    async with await get_gitlab_client() as client:
        try:
            # Create branch
            log.debug(f"Creating branch {source_branch}")
            await client.post(
                f"/projects/{project_id}/repository/branches",
                json={"branch": source_branch, "ref": target_branch}
            )
            
            # Create commits
            actions = []
            for file_path, content in files.items():
                actions.append({
                    "action": "update",
                    "file_path": file_path,
                    "content": content
                })
            
            log.debug(f"Committing {len(actions)} file changes")
            await client.post(
                f"/projects/{project_id}/repository/commits",
                json={
                    "branch": source_branch,
                    "commit_message": title,
                    "actions": actions
                }
            )
            
            # Create MR
            log.debug("Creating merge request")
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
            mr = response.json()
            log.info(f"Created MR: {mr.get('web_url')}")
            return mr
            
        except Exception as e:
            log.error(f"Failed to create merge request: {e}")
            return {"error": str(e)}

@tool
async def get_project_info(project_id: str) -> Dict[str, Any]:
    """Get project information
    
    Args:
        project_id: GitLab project ID
    
    Returns:
        Project details
    """
    log.info(f"Getting info for project {project_id}")
    
    async with await get_gitlab_client() as client:
        try:
            response = await client.get(f"/projects/{project_id}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error(f"Failed to get project info: {e}")
            return {"error": str(e)}