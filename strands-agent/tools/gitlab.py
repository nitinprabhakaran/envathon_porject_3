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
    """Get all jobs in a pipeline to identify which ones failed and their status.
    
    Essential first step in pipeline failure analysis. Use this to discover
    which specific jobs failed and need detailed investigation.
    
    Args:
        pipeline_id: GitLab pipeline ID from the webhook
        project_id: GitLab numeric project ID
    
    Returns:
        List of job dictionaries with status, stage, name, and timing information
        Look for jobs with status='failed' to identify failure points
        
    Job Properties:
        - id: Job ID (use with get_job_logs)
        - name: Job name (e.g., 'build', 'test', 'sonarqube-check')
        - stage: Pipeline stage (e.g., 'build', 'test', 'quality')
        - status: 'success', 'failed', 'running', etc.
        - started_at, finished_at: Timing information
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
    """Get execution logs from a specific GitLab CI/CD job for failure analysis.
    
    Essential for diagnosing pipeline failures - provides detailed error messages,
    compilation errors, test failures, and other diagnostic information.
    
    Args:
        job_id: GitLab job ID (numeric string)
        project_id: GitLab numeric project ID
        max_size: Maximum log size in characters (default: 30000 for context efficiency)
    
    Returns:
        Job log content as text, truncated if necessary to fit context limits
        
    Usage Tips:
        - Always specify max_size=30000 for large logs to prevent context overflow
        - Focus on error messages and failure indicators in the returned logs
        - Look for compilation errors, test failures, or configuration issues
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
    """Retrieve source code files to understand project structure and identify issues.
    
    Use this to examine configuration files, source code, and other project files
    when analyzing failures or preparing fixes.
    
    Args:
        file_path: Repository file path (e.g., 'src/main/App.java', '.gitlab-ci.yml', 'package.json')
        project_id: GitLab numeric project ID
        ref: Git reference - branch, tag, or commit SHA (default: "HEAD" for latest)
    
    Returns:
        File content as string, or error message if file not found
        
    Common Files to Examine:
        - CI/CD configs: '.gitlab-ci.yml', 'Jenkinsfile'
        - Dependencies: 'package.json', 'pom.xml', 'requirements.txt'
        - Config files: 'sonar-project.properties', 'Dockerfile'
        - Source code: Files mentioned in error logs
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
                return f"Error: File '{file_path}' does not exist in the repository"
            
            if response.status_code == 200:
                # Return content directly for Bedrock API compatibility
                content = response.text
                if len(content) > 50000:  # Limit very large files
                    content = content[:50000] + "\n... [File truncated due to size]"
                
                return content
            
            # Try alternative API endpoint
            url = f"/projects/{project_id}/repository/files/{encoded_path}"
            response = await client.get(url, params={"ref": ref})
            
            if response.status_code == 404:
                log.info(f"File {file_path} not found in project {project_id}")
                return f"Error: File '{file_path}' does not exist in the repository"
                
            if response.status_code == 200:
                # Decode base64 content
                import base64
                data = response.json()
                content = base64.b64decode(data['content']).decode('utf-8')
                
                # Return content directly for Bedrock API compatibility
                if len(content) > 50000:  # Limit very large files
                    content = content[:50000] + "\n... [File truncated due to size]"
                
                return content
            
            response.raise_for_status()
            return f"Error: HTTP {response.status_code} getting file content"
            
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
    files: Dict[str, Any],
    project_id: str,
    source_branch: str,
    target_branch: str = "main",
    update_mode: bool = False
) -> Dict[str, Any]:
    """Create or update a merge request with file changes
    
    Args:
        title: MR title
        description: MR description
        files: Dict with 'updates' and 'creates' keys, each containing file paths and content
        project_id: GitLab project ID
        source_branch: Source branch name
        target_branch: Target branch (default: main)
        update_mode: If True, commits to existing branch without creating it
    
    Returns:
        Dictionary with MR details or error information
    """
    
    async with await get_gitlab_client() as client:
        try:
            # Check if branch exists with proper encoding
            branch_exists = False
            try:
                encoded_branch = quote(source_branch, safe='')
                branch_check = await client.get(f"/projects/{project_id}/repository/branches/{encoded_branch}")
                if branch_check.status_code == 200:
                    branch_exists = True
                    log.info(f"Branch {source_branch} exists")
                else:
                    log.debug(f"Branch {source_branch} does not exist (status: {branch_check.status_code})")
            except Exception as e:
                log.debug(f"Branch check for {source_branch}: {e}")
                branch_exists = False
            
            # If in update mode, we expect the branch to exist
            if update_mode and not branch_exists:
                log.error(f"Update mode requested but branch {source_branch} doesn't exist")
                return {"error": f"Branch {source_branch} not found for update"}
                
            if update_mode:
                log.info(f"Updating existing branch {source_branch}")
            
            # Process files
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
            
            # Determine which branch to check files against
            if branch_exists:
                check_ref = source_branch
            else:
                check_ref = target_branch
            
            # Check each file's actual existence
            for intended_action, file_path, content in files_to_process:
                encoded_path = quote(file_path, safe='')
                
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
                    files_processed.append(f"CREATE: {file_path}")
                    log.info(f"File {file_path} doesn't exist on {check_ref}, creating it")
            
            if not actions:
                return {
                    "error": "No files to commit",
                    "files_checked": files_processed
                }
            
            # Prepare commit - key fix is here
            commit_data = {
                "branch": source_branch,
                "commit_message": f"Fix: {title}",
                "actions": actions
            }
            
            # Only add start_branch if creating new branch
            if not branch_exists:
                commit_data["start_branch"] = target_branch
                log.info(f"Creating new branch {source_branch} from {target_branch}")
            
            # Make the commit
            commit_response = await client.post(
                f"/projects/{project_id}/repository/commits",
                json=commit_data
            )
            
            if commit_response.status_code != 201:
                log.error(f"Commit failed with status {commit_response.status_code}: {commit_response.text}")
                return {
                    "error": f"Commit failed: {commit_response.text}",
                    "files_processed": files_processed,
                    "branch_exists": branch_exists,
                    "update_mode": update_mode,
                    "generated_branch": source_branch
                }
            
            log.info(f"Successfully committed to branch {source_branch}")
            commit_sha = commit_response.json().get("id")
            
            # Handle MR creation/update
            if branch_exists or update_mode:
                # Branch exists, check for existing MR
                mrs_response = await client.get(
                    f"/projects/{project_id}/merge_requests",
                    params={"source_branch": source_branch, "state": "opened"}
                )
                
                if mrs_response.status_code == 200:
                    mrs = mrs_response.json()
                    if mrs:
                        mr = mrs[0]
                        log.info(f"Found existing MR !{mr.get('iid')}")
                        return {
                            "id": mr.get("iid"),
                            "web_url": mr.get("web_url"),
                            "message": "Updated existing merge request",
                            "branch": source_branch,
                            "files_processed": files_processed,
                            "commit_sha": commit_sha
                        }
                
                # No existing MR but branch exists
                return {
                    "message": "Committed to existing branch",
                    "branch": source_branch,
                    "files_processed": files_processed,
                    "commit_sha": commit_sha,
                    "info": "No merge request found for this branch"
                }
            
            else:
                # New branch, create MR
                mr_description = (
                    f"{description}\n\n"
                    f"**Files changed:**\n" + "\n".join(f"- {fp}" for fp in files_processed)
                )
                
                mr_response = await client.post(
                    f"/projects/{project_id}/merge_requests",
                    json={
                        "source_branch": source_branch,
                        "target_branch": target_branch,
                        "title": title,
                        "description": mr_description,
                        "remove_source_branch": True
                    }
                )
                
                if mr_response.status_code != 201:
                    log.error(f"MR creation failed: {mr_response.text}")
                    return {
                        "error": f"MR creation failed: {mr_response.text}",
                        "branch": source_branch,
                        "commit_sha": commit_sha
                    }
                
                mr_data = mr_response.json()
                log.info(f"Created new MR !{mr_data.get('iid')}")
                return {
                    "id": mr_data.get("iid"),
                    "web_url": mr_data.get("web_url"),
                    "title": mr_data.get("title"),
                    "source_branch": source_branch,
                    "target_branch": target_branch,
                    "files_processed": files_processed,
                    "commit_sha": commit_sha
                }
                
        except Exception as e:
            log.error(f"Failed to create/update merge request: {e}", exc_info=True)
            return {"error": str(e)}

@tool
async def get_project_info(project_id: str) -> Dict[str, Any]:
    """Get basic project information and metadata from GitLab.
    
    Useful for understanding project context, default branch, and basic settings.
    
    Args:
        project_id: GitLab numeric project ID (not project name)
    
    Returns:
        Project details including name, description, default_branch, web_url, etc.
        Returns error dict if project not found or access denied
        
    Common Use Cases:
        - Verify project exists and is accessible
        - Get default branch name for file operations
        - Understand project context and settings
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

@tool
async def get_merge_request_details(project_id: str, mr_iid: str) -> Dict[str, Any]:
    """Get merge request details by IID
    
    Args:
        project_id: GitLab project ID
        mr_iid: Merge request internal ID
    
    Returns:
        MR details including source_branch, web_url, etc.
    """
    log.info(f"Getting MR details for !{mr_iid} in project {project_id}")
    
    async with await get_gitlab_client() as client:
        try:
            response = await client.get(f"/projects/{project_id}/merge_requests/{mr_iid}")
            response.raise_for_status()
            mr = response.json()
            
            return {
                "iid": mr.get("iid"),
                "web_url": mr.get("web_url"),
                "source_branch": mr.get("source_branch"),
                "target_branch": mr.get("target_branch"),
                "title": mr.get("title"),
                "state": mr.get("state")
            }
        except Exception as e:
            log.error(f"Failed to get MR details: {e}")
            return {"error": str(e)}