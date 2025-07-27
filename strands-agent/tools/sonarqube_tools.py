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

@tool
async def get_project_quality_status(project_id: Optional[str] = None) -> Dict[str, Any]:
    """Get overall quality status from SonarQube
    
    Args:
        project_id: SonarQube project key (same as project name)
    
    Returns:
        Project quality status including quality gate, metrics, and ratings
    """
    # Get from context if not provided
    if not project_id:
        try:
            import inspect
            frame = inspect.currentframe()
            while frame:
                frame_locals = frame.f_locals
                if 'self' in frame_locals:
                    agent = frame_locals['self']
                    if hasattr(agent, 'session_state'):
                        project_id = agent.session_state.get("sonarqube_key")
                        break
                frame = frame.f_back
        except:
            pass
    
    if not project_id:
        return {"error": "Project ID not found"}
    
    async with await get_sonar_client() as client:
        try:
            # Get project status
            response = await client.get(
                "/qualitygates/project_status",
                params={"projectKey": project_id}
            )
            response.raise_for_status()
            status_data = response.json()
            
            # Get project metrics
            metrics_response = await client.get(
                "/measures/component",
                params={
                    "component": project_id,
                    "metricKeys": "bugs,vulnerabilities,code_smells,coverage,duplicated_lines_density,reliability_rating,security_rating,maintainability_rating"
                }
            )
            metrics_response.raise_for_status()
            metrics_data = metrics_response.json()
            
            return {
                "project_key": project_id,
                "quality_gate": status_data.get("projectStatus", {}),
                "metrics": metrics_data.get("component", {}).get("measures", [])
            }
            
        except Exception as e:
            logger.error(f"Failed to get project quality status: {e}")
            return {"error": str(e), "project_key": project_id}

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
        project_id: SonarQube project key
    
    Returns:
        List of code quality issues with details
    """
    # Get from context if not provided
    if not project_id:
        try:
            import inspect
            frame = inspect.currentframe()
            while frame:
                frame_locals = frame.f_locals
                if 'self' in frame_locals:
                    agent = frame_locals['self']
                    if hasattr(agent, 'session_state'):
                        project_id = agent.session_state.get("sonarqube_key")
                        break
                frame = frame.f_back
        except:
            pass
    
    if not project_id:
        return []
    
    async with await get_sonar_client() as client:
        try:
            params = {
                "componentKeys": project_id,
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
            return []

@tool
async def get_security_vulnerabilities(project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get security vulnerabilities from SonarQube
    
    Args:
        project_id: SonarQube project key
    
    Returns:
        List of security vulnerabilities with severity and details
    """
    # This is a specialized version of get_code_quality_issues focused on vulnerabilities
    vulnerabilities = await get_code_quality_issues(
        issue_type="VULNERABILITY",
        project_id=project_id
    )
    
    # Get security hotspots as well
    if not project_id:
        try:
            import inspect
            frame = inspect.currentframe()
            while frame:
                frame_locals = frame.f_locals
                if 'self' in frame_locals:
                    agent = frame_locals['self']
                    if hasattr(agent, 'session_state'):
                        project_id = agent.session_state.get("sonarqube_key")
                        break
                frame = frame.f_back
        except:
            pass
    
    if not project_id:
        return vulnerabilities
    
    async with await get_sonar_client() as client:
        try:
            response = await client.get(
                "/hotspots/search",
                params={"projectKey": project_id}
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
            return vulnerabilities

@tool
async def get_quality_gate_details(project_key: str) -> Dict[str, Any]:
    """Get detailed quality gate status and conditions
    
    Args:
        project_key: SonarQube project key
    
    Returns:
        Quality gate details including conditions and metrics
    """
    async with await get_sonar_client() as client:
        try:
            response = await client.get(
                "/qualitygates/project_status",
                params={"projectKey": project_key}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get quality gate details: {e}")
            return {"error": str(e)}

@tool
async def check_project_exists(project_key: str) -> bool:
    """Check if a project exists in SonarQube"""
    async with await get_sonar_client() as client:
        try:
            response = await client.get(
                "/projects/search",
                params={"projects": project_key}
            )
            response.raise_for_status()
            data = response.json()
            components = data.get("components", [])
            return any(c.get("key") == project_key for c in components)
        except:
            return False

@tool
async def get_issues_with_context(
    project_key: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get all SonarQube issues with file paths and line numbers"""
    if not project_key:
        # Get from context
        try:
            import inspect
            frame = inspect.currentframe()
            while frame:
                frame_locals = frame.f_locals
                if 'self' in frame_locals:
                    agent = frame_locals['self']
                    if hasattr(agent, 'session_state'):
                        project_key = agent.session_state.get("sonarqube_key")
                        break
                frame = frame.f_back
        except:
            pass
    
    if not project_key:
        return []
    
    # Check if project exists first
    if not await check_project_exists(project_key):
        logger.warning(f"Project {project_key} not found in SonarQube")
        return []
    
    async with await get_sonar_client() as client:
        try:
            response = await client.get(
                "/issues/search",
                params={
                    "componentKeys": project_key,
                    "ps": limit,
                    "resolved": "false"
                }
            )
            response.raise_for_status()
            
            issues = []
            for issue in response.json().get("issues", []):
                component = issue.get("component", "")
                file_path = component.split(":")[-1] if ":" in component else component
                
                issues.append({
                    "key": issue.get("key"),
                    "file_path": file_path,
                    "line": issue.get("line"),
                    "type": issue.get("type"),
                    "severity": issue.get("severity"),
                    "message": issue.get("message"),
                    "rule": issue.get("rule"),
                    "effort": issue.get("effort")
                })
            
            return issues
            
        except Exception as e:
            logger.error(f"Failed to get issues: {e}")
            return []