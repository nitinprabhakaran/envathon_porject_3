import os
from typing import Dict, Any, List, Optional
import httpx
from strands import tool
from loguru import logger
import base64

# SonarQube configuration
SONAR_HOST_URL = os.getenv("SONAR_HOST_URL", "http://sonarqube:9000")
SONAR_TOKEN = os.getenv("SONAR_TOKEN", "")

# HTTP client for SonarQube API
async def get_sonar_client():
    auth_header = {}
    if SONAR_TOKEN:
        # SonarQube uses basic auth with token as username and empty password
        credentials = base64.b64encode(f"{SONAR_TOKEN}:".encode()).decode()
        auth_header = {"Authorization": f"Basic {credentials}"}
    
    return httpx.AsyncClient(
        base_url=f"{SONAR_HOST_URL}/api",
        headers=auth_header,
        timeout=30.0
    )

async def get_sonar_project_key(project_id: Optional[str] = None) -> str:
    """Get SonarQube project key from GitLab project ID"""
    if not project_id:
        # Try to get from context
        try:
            from strands import Agent
            current_agent = getattr(Agent, '_current_instance', None)
            if current_agent and hasattr(current_agent, 'session_state'):
                project_id = current_agent.session_state.get("project_id")
        except:
            project_id = "default"
    
    # Get project details from GitLab to get the project name
    from .gitlab_tools import get_gitlab_client
    async with await get_gitlab_client() as client:
        try:
            response = await client.get(f"/projects/{project_id}")
            response.raise_for_status()
            project_data = response.json()
            project_name = project_data.get("name", project_id)
            
            # Return SonarQube project key format
            return f"envathon_{project_name}"
        except Exception as e:
            logger.warning(f"Failed to get project name from GitLab: {e}")
            # Fallback to project ID
            return f"envathon_project_{project_id}"

@tool
async def get_project_quality_status(project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get overall quality status from SonarQube
    
    Args:
        project_id: GitLab project ID (will be converted to SonarQube key)
    
    Returns:
        Project quality status including quality gate, metrics, and ratings
    """
    project_key = await get_sonar_project_key(project_id)
    
    async with await get_sonar_client() as client:
        try:
            # Get project status
            response = await client.get(
                "/qualitygates/project_status",
                params={"projectKey": project_key}
            )
            response.raise_for_status()
            status_data = response.json()
            
            # Get project metrics
            metrics_response = await client.get(
                "/measures/component",
                params={
                    "component": project_key,
                    "metricKeys": "bugs,vulnerabilities,code_smells,coverage,duplicated_lines_density,reliability_rating,security_rating,maintainability_rating"
                }
            )
            metrics_response.raise_for_status()
            metrics_data = metrics_response.json()
            
            return {
                "project_key": project_key,
                "quality_gate": status_data.get("projectStatus", {}),
                "metrics": metrics_data.get("component", {}).get("measures", [])
            }
            
        except Exception as e:
            logger.error(f"Failed to get project quality status: {e}")
            return {"error": str(e), "project_key": project_key}

@tool
async def get_code_quality_issues(
    severity: Optional[str] = None,
    issue_type: Optional[str] = None,
    project_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get code quality issues from SonarQube
    
    Args:
        severity: Filter by severity (BLOCKER, CRITICAL, MAJOR, MINOR, INFO)
        issue_type: Filter by type (BUG, VULNERABILITY, CODE_SMELL)
        project_id: GitLab project ID (will be converted to SonarQube key)
    
    Returns:
        List of code quality issues with details
    """
    project_key = await get_sonar_project_key(project_id)
    
    async with await get_sonar_client() as client:
        try:
            params = {
                "componentKeys": project_key,
                "ps": 50,  # Page size
                "resolved": "false"
            }
            
            if severity:
                params["severities"] = severity.upper()
            if issue_type:
                params["types"] = issue_type.upper()
            
            response = await client.get("/issues/search", params=params)
            response.raise_for_status()
            
            data = response.json()
            issues = data.get("issues", [])
            
            # Simplify the response
            simplified_issues = []
            for issue in issues:
                simplified_issues.append({
                    "key": issue.get("key"),
                    "type": issue.get("type"),
                    "severity": issue.get("severity"),
                    "message": issue.get("message"),
                    "component": issue.get("component"),
                    "line": issue.get("line"),
                    "effort": issue.get("effort"),
                    "debt": issue.get("debt"),
                    "rule": issue.get("rule")
                })
            
            return simplified_issues
            
        except Exception as e:
            logger.error(f"Failed to get code quality issues: {e}")
            return [{"error": str(e)}]

@tool
async def get_security_vulnerabilities(project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get security vulnerabilities from SonarQube
    
    Args:
        project_id: GitLab project ID (will be converted to SonarQube key)
    
    Returns:
        List of security vulnerabilities with severity and details
    """
    # This is a specialized version of get_code_quality_issues focused on vulnerabilities
    vulnerabilities = await get_code_quality_issues(
        issue_type="VULNERABILITY",
        project_id=project_id
    )
    
    # Get security hotspots as well
    project_key = await get_sonar_project_key(project_id)
    
    async with await get_sonar_client() as client:
        try:
            response = await client.get(
                "/hotspots/search",
                params={"projectKey": project_key}
            )
            response.raise_for_status()
            
            hotspots_data = response.json()
            hotspots = hotspots_data.get("hotspots", [])
            
            # Add hotspots to vulnerabilities list
            for hotspot in hotspots:
                vulnerabilities.append({
                    "key": hotspot.get("key"),
                    "type": "SECURITY_HOTSPOT",
                    "severity": hotspot.get("vulnerabilityProbability", "MEDIUM"),
                    "message": hotspot.get("message"),
                    "component": hotspot.get("component"),
                    "line": hotspot.get("line"),
                    "category": hotspot.get("securityCategory"),
                    "status": hotspot.get("status")
                })
            
            return vulnerabilities
            
        except Exception as e:
            logger.error(f"Failed to get security hotspots: {e}")
            return vulnerabilities  # Return what we have even if hotspots fail