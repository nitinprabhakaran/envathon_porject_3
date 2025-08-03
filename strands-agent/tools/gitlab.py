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
async def get_file_content(file_path: str, project_id: str, ref: str = "HEAD") -> Dict[str, Any]:
    """Get content of a file from GitLab repository
    
    Args:
        file_path: Path to file in repository
        project_id: GitLab project ID
        ref: Git reference (branch, tag, or commit SHA)
    
    Returns:
        Dictionary with 'status' and either 'content' or 'error'
    """
    log.info(f"Getting file {file_path} from project {project_id} at ref {ref}")
    
    async with await get_gitlab_client() as client:
        try:
            # URL encode the file path - replace / with %2F
            encoded_path = quote(file_path, safe='')
            
            # Try raw endpoint first
            url = f"/projects/{project_id}/repository/files/{encoded_path}/raw"
            response = await client.get(url, params={"ref": ref})
            
            if response.status_code == 404:
                # File doesn't exist
                log.info(f"File {file_path} not found in project {project_id}")
                return {
                    "status": "not_found",
                    "error": f"File '{file_path}' does not exist in the repository",
                    "file_path": file_path
                }
            
            if response.status_code == 200:
                return {
                    "status": "success",
                    "content": response.text,
                    "file_path": file_path
                }
            
            # Try alternative API endpoint
            url = f"/projects/{project_id}/repository/files/{encoded_path}"
            response = await client.get(url, params={"ref": ref})
            
            if response.status_code == 404:
                log.info(f"File {file_path} not found in project {project_id}")
                return {
                    "status": "not_found",
                    "error": f"File '{file_path}' does not exist in the repository",
                    "file_path": file_path
                }
                
            if response.status_code == 200:
                # Decode base64 content
                import base64
                data = response.json()
                content = base64.b64decode(data['content']).decode('utf-8')
                return {
                    "status": "success",
                    "content": content,
                    "file_path": file_path
                }
            
            response.raise_for_status()
            
        except Exception as e:
            log.error(f"Failed to get file content: {e}")
            return {
                "status": "error",
                "error": str(e),
                "file_path": file_path
            }

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
    files: Dict[str, Any],
    project_id: str,
    source_branch: str,
    target_branch: str = "main",
    update_mode: bool = False
) -> Dict[str, Any]:
    """Create or update a merge request with file changes
    
    Args:
        files: Dict with 'updates' and 'creates' keys, each containing file paths and content
    """
    
    async with await get_gitlab_client() as client:
        try:
            branch_exists = False
            try:
                branch_check = await client.get(f"/projects/{project_id}/repository/branches/{source_branch}")
                if branch_check.status_code == 200:
                    branch_exists = True
                    log.info(f"Branch {source_branch} already exists")
            except:
                pass
            
            if not branch_exists and not update_mode:
                # Create new branch from target
                await client.post(
                    f"/projects/{project_id}/repository/branches",
                    json={"branch": source_branch, "ref": target_branch}
                )
            elif branch_exists:
                update_mode = True
                log.info(f"Switching to update mode for existing branch {source_branch}")
            
            # Process updates and creates based on LLM instructions
            files_to_process = []
            
            if isinstance(files, dict) and "updates" in files:
                for file_path, content in files["updates"].items():
                    files_to_process.append(("update", file_path, content))
                    log.info(f"LLM marked for update: {file_path}")
            
            if isinstance(files, dict) and "creates" in files:
                for file_path, content in files["creates"].items():
                    files_to_process.append(("create", file_path, content))
                    log.info(f"LLM marked for create: {file_path}")
            
            # Fallback for old format
            if not any(key in files for key in ["updates", "creates"]):
                log.warning("Using legacy file format")
                for file_path, content in files.items():
                    files_to_process.append(("update", file_path, content))
            
            actions = []
            files_processed = []
            
            # Now check each file's actual existence
            for intended_action, file_path, content in files_to_process:
                encoded_path = quote(file_path, safe='')
                
                # For new branches, check against target branch since source doesn't have files yet
                check_ref = target_branch if not update_mode else source_branch
                
                # Check if file exists
                file_exists = False
                try:
                    check_response = await client.get(
                        f"/projects/{project_id}/repository/files/{encoded_path}",
                        params={"ref": check_ref}
                    )
                    if check_response.status_code == 200:
                        file_exists = True
                except:
                    file_exists = False
                
                # Determine the correct action
                if file_exists:
                    actions.append({"action": "update", "file_path": file_path, "content": content})
                    files_processed.append(f"UPDATE: {file_path}")
                else:
                    actions.append({"action": "create", "file_path": file_path, "content": content})
                    files_processed.append(f"CREATE: {file_path} (file doesn't exist on {check_ref})")
                    log.warning(f"File {file_path} doesn't exist on {check_ref}, creating it")
            
            if not actions:
                return {
                    "error": "No files to commit",
                    "files_checked": files_processed
                }
            
            # Commit changes
            commit_response = await client.post(
                f"/projects/{project_id}/repository/commits",
                json={
                    "branch": source_branch,
                    "commit_message": f"Fix: {title}",
                    "actions": actions
                }
            )
            
            if commit_response.status_code != 201:
                log.error(f"Commit failed: {commit_response.text}")
                return {
                    "error": f"Commit failed: {commit_response.text}",
                    "files_processed": files_processed
                }
            
            if not update_mode:
                # Create new MR
                response = await client.post(
                    f"/projects/{project_id}/merge_requests",
                    json={
                        "source_branch": source_branch,
                        "target_branch": target_branch,
                        "title": title,
                        "description": description + f"\n\n**Files changed:**\n" + "\n".join(f"- {fp}" for fp in files_processed),
                        "remove_source_branch": True
                    }
                )
                
                if response.status_code != 201:
                    log.error(f"MR creation failed: {response.text}")
                    return {"error": f"MR creation failed: {response.text}"}
                    
                mr_data = response.json()
                return {
                    "id": mr_data.get("iid"),
                    "web_url": mr_data.get("web_url"),
                    "title": mr_data.get("title"),
                    "source_branch": source_branch,
                    "target_branch": target_branch,
                    "files_processed": files_processed
                }
            else:
                # Return existing MR info - we need to find it
                mrs_response = await client.get(
                    f"/projects/{project_id}/merge_requests",
                    params={"source_branch": source_branch, "state": "opened"}
                )
                if mrs_response.status_code == 200:
                    mrs = mrs_response.json()
                    if mrs:
                        mr = mrs[0]
                        return {
                            "id": mr.get("iid"),
                            "web_url": mr.get("web_url"),
                            "message": "Added commits to existing branch",
                            "branch": source_branch,
                            "files_processed": files_processed
                        }
                
                return {
                    "message": "Added commits to existing branch",
                    "branch": source_branch,
                    "files_processed": files_processed
                }
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