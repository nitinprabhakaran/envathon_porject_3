"""SonarQube tools for quality analysis"""
import httpx
import base64
from typing import Dict, Any, List, Optional
from strands import tool
from utils.logger import log
from config import settings

async def get_sonar_client():
    """Create SonarQube API client"""
    auth_header = {}
    if settings.sonar_token:
        credentials = base64.b64encode(f"{settings.sonar_token}:".encode()).decode()
        auth_header = {"Authorization": f"Basic {credentials}"}
    
    return httpx.AsyncClient(
        base_url=f"{settings.sonar_host_url}/api",
        headers=auth_header,
        timeout=30.0
    )

@tool
async def get_project_quality_gate_status(project_key: str) -> Dict[str, Any]:
    """Get quality gate status for a project
    
    Args:
        project_key: SonarQube project key
    
    Returns:
        Quality gate status and conditions
    """
    log.info(f"Getting quality gate status for {project_key}")
    
    async with await get_sonar_client() as client:
        try:
            response = await client.get(
                "/qualitygates/project_status",
                params={"projectKey": project_key}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error(f"Failed to get quality gate status: {e}")
            return {"error": str(e)}

@tool
async def get_project_issues(
    project_key: str,
    types: Optional[str] = None,
    severities: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Get issues for a project
    
    Args:
        project_key: SonarQube project key
        types: Comma-separated issue types (BUG,VULNERABILITY,CODE_SMELL)
        severities: Comma-separated severities (BLOCKER,CRITICAL,MAJOR,MINOR,INFO)
        limit: Maximum number of issues
    
    Returns:
        List of issues with details
    """
    log.info(f"Getting issues for {project_key} (types={types}, severities={severities})")
    
    async with await get_sonar_client() as client:
        try:
            params = {
                "componentKeys": project_key,
                "ps": limit,
                "resolved": "false"
            }
            if types:
                params["types"] = types
            if severities:
                params["severities"] = severities
            
            response = await client.get("/issues/search", params=params)
            response.raise_for_status()
            
            issues = response.json().get("issues", [])
            log.debug(f"Found {len(issues)} issues")
            
            # Simplify response
            return [{
                "key": issue.get("key"),
                "type": issue.get("type"),
                "severity": issue.get("severity"),
                "message": issue.get("message"),
                "component": issue.get("component"),
                "line": issue.get("line"),
                "effort": issue.get("effort"),
                "rule": issue.get("rule"),
                "file": issue.get("component", "").split(":")[-1] if ":" in issue.get("component", "") else issue.get("component")
            } for issue in issues]
            
        except Exception as e:
            log.error(f"Failed to get project issues: {e}")
            return []

@tool
async def get_project_metrics(project_key: str) -> Dict[str, Any]:
    """Get project metrics
    
    Args:
        project_key: SonarQube project key
    
    Returns:
        Project metrics including coverage, duplications, etc.
    """
    log.info(f"Getting metrics for {project_key}")
    
    async with await get_sonar_client() as client:
        try:
            response = await client.get(
                "/measures/component",
                params={
                    "component": project_key,
                    "metricKeys": "bugs,vulnerabilities,code_smells,coverage,duplicated_lines_density,reliability_rating,security_rating,sqale_rating,ncloc"
                }
            )
            response.raise_for_status()
            
            measures = response.json().get("component", {}).get("measures", [])
            
            # Convert to dict for easier access
            metrics = {}
            for measure in measures:
                metric_key = measure["metric"]
                # Map sqale_rating to maintainability_rating
                if metric_key == "sqale_rating":
                    metrics["maintainability_rating"] = measure.get("value", "E")
                else:
                    metrics[metric_key] = measure.get("value", measure.get("periods", [{}])[0].get("value", "N/A"))
            
            return metrics
            
        except Exception as e:
            log.error(f"Failed to get project metrics: {e}")
            return {"error": str(e)}

@tool
async def get_issue_details(issue_key: str) -> Dict[str, Any]:
    """Get detailed information about an issue
    
    Args:
        issue_key: SonarQube issue key
    
    Returns:
        Detailed issue information
    """
    log.info(f"Getting details for issue {issue_key}")
    
    async with await get_sonar_client() as client:
        try:
            response = await client.get(
                "/issues/search",
                params={"issues": issue_key}
            )
            response.raise_for_status()
            
            issues = response.json().get("issues", [])
            if issues:
                return issues[0]
            return {"error": "Issue not found"}
            
        except Exception as e:
            log.error(f"Failed to get issue details: {e}")
            return {"error": str(e)}

@tool
async def get_rule_description(rule_key: str) -> Dict[str, Any]:
    """Get rule description and remediation guidance
    
    Args:
        rule_key: SonarQube rule key
    
    Returns:
        Rule details including description and examples
    """
    log.info(f"Getting rule description for {rule_key}")
    
    async with await get_sonar_client() as client:
        try:
            response = await client.get(
                "/rules/show",
                params={"key": rule_key}
            )
            response.raise_for_status()
            
            rule = response.json().get("rule", {})
            return {
                "key": rule.get("key"),
                "name": rule.get("name"),
                "severity": rule.get("severity"),
                "type": rule.get("type"),
                "description": rule.get("htmlDesc", ""),
                "remediation": rule.get("remFnBaseEffort", "")
            }
            
        except Exception as e:
            log.error(f"Failed to get rule description: {e}")
            return {"error": str(e)}