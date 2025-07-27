from typing import Dict, Any, List, Optional
from strands import tool
from loguru import logger
import json

from tools.sonarqube_tools import get_code_quality_issues
from tools.gitlab_tools import create_merge_request

@tool
async def analyze_quality_gate(
    project_key: str,
    conditions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Analyze quality gate failure conditions
    
    Args:
        project_key: SonarQube project key
        conditions: Failed quality gate conditions
    
    Returns:
        Analysis of what caused the quality gate to fail
    """
    analysis = {
        "project_key": project_key,
        "failed_metrics": [],
        "severity_breakdown": {
            "critical": 0,
            "major": 0,
            "minor": 0
        },
        "categories": {
            "reliability": [],
            "security": [],
            "maintainability": []
        }
    }
    
    for condition in conditions:
        if condition.get("status") == "ERROR":
            metric = condition.get("metric", "")
            value = condition.get("value", "")
            
            failed_metric = {
                "metric": metric,
                "value": value,
                "threshold": condition.get("errorThreshold", ""),
                "operator": condition.get("operator", "")
            }
            
            # Categorize by type
            if "reliability" in metric or "bug" in metric:
                analysis["categories"]["reliability"].append(failed_metric)
            elif "security" in metric or "vulnerabilit" in metric:
                analysis["categories"]["security"].append(failed_metric)
            else:
                analysis["categories"]["maintainability"].append(failed_metric)
            
            analysis["failed_metrics"].append(failed_metric)
    
    return analysis

@tool
async def categorize_issues(
    issues: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    """Categorize issues by type and severity
    
    Args:
        issues: List of SonarQube issues
    
    Returns:
        Issues grouped by category
    """
    categorized = {
        "bugs": [],
        "vulnerabilities": [],
        "code_smells": [],
        "by_severity": {
            "BLOCKER": [],
            "CRITICAL": [],
            "MAJOR": [],
            "MINOR": [],
            "INFO": []
        },
        "by_effort": {
            "quick_wins": [],  # < 10 min
            "medium_effort": [],  # 10-60 min
            "high_effort": []  # > 60 min
        }
    }
    
    for issue in issues:
        issue_type = issue.get("type", "").lower()
        severity = issue.get("severity", "")
        effort = issue.get("effort", "0min")
        
        # By type
        if issue_type == "bug":
            categorized["bugs"].append(issue)
        elif issue_type == "vulnerability":
            categorized["vulnerabilities"].append(issue)
        elif issue_type == "code_smell":
            categorized["code_smells"].append(issue)
        
        # By severity
        if severity in categorized["by_severity"]:
            categorized["by_severity"][severity].append(issue)
        
        # By effort
        effort_minutes = _parse_effort(effort)
        if effort_minutes < 10:
            categorized["by_effort"]["quick_wins"].append(issue)
        elif effort_minutes <= 60:
            categorized["by_effort"]["medium_effort"].append(issue)
        else:
            categorized["by_effort"]["high_effort"].append(issue)
    
    return categorized

@tool
async def suggest_batch_fixes(
    categorized_issues: Dict[str, List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """Suggest batch fixes for similar issues
    
    Args:
        categorized_issues: Issues grouped by category
    
    Returns:
        List of batch fix suggestions
    """
    suggestions = []
    
    # Group similar code smells
    code_smells = categorized_issues.get("code_smells", [])
    smell_groups = {}
    
    for smell in code_smells:
        rule = smell.get("rule", "")
        if rule not in smell_groups:
            smell_groups[rule] = []
        smell_groups[rule].append(smell)
    
    # Create batch suggestions
    for rule, issues in smell_groups.items():
        if len(issues) > 2:  # Only batch if 3+ similar issues
            total_effort = sum(_parse_effort(i.get("effort", "0min")) for i in issues)
            
            suggestions.append({
                "type": "batch_fix",
                "rule": rule,
                "issue_count": len(issues),
                "total_effort_minutes": total_effort,
                "description": f"Fix {len(issues)} instances of {rule}",
                "files_affected": len(set(i.get("component", "") for i in issues)),
                "issues": issues
            })
    
    # Security fixes should be individual but prioritized
    vulnerabilities = categorized_issues.get("vulnerabilities", [])
    if vulnerabilities:
        suggestions.append({
            "type": "security_batch",
            "issue_count": len(vulnerabilities),
            "description": "Fix all security vulnerabilities",
            "priority": "HIGH",
            "issues": vulnerabilities
        })
    
    # Quick wins batch
    quick_wins = categorized_issues.get("by_effort", {}).get("quick_wins", [])
    if len(quick_wins) > 5:
        suggestions.append({
            "type": "quick_wins",
            "issue_count": len(quick_wins),
            "total_effort_minutes": sum(_parse_effort(i.get("effort", "0min")) for i in quick_wins),
            "description": f"Fix {len(quick_wins)} quick win issues",
            "issues": quick_wins
        })
    
    return suggestions

@tool
async def create_quality_mr(
    session_id: str,
    batch_fix: Dict[str, Any],
    project_id: str
) -> Dict[str, Any]:
    """Create a merge request for quality fixes
    
    Args:
        session_id: Quality session ID
        batch_fix: Batch fix details
        project_id: GitLab project ID
    
    Returns:
        Created MR details
    """
    # Generate fix content based on issues
    issues = batch_fix.get("issues", [])
    fix_type = batch_fix.get("type", "quality_fix")
    
    # Group fixes by file
    file_fixes = {}
    for issue in issues:
        component = issue.get("component", "")
        if component not in file_fixes:
            file_fixes[component] = []
        file_fixes[component].append(issue)
    
    # Create MR description
    description = f"""## 🔧 Quality Fixes

This MR addresses {len(issues)} quality issues identified by SonarQube.

### Issues Fixed:
"""
    
    # Add issue details
    by_type = {}
    for issue in issues:
        issue_type = issue.get("type", "UNKNOWN")
        if issue_type not in by_type:
            by_type[issue_type] = []
        by_type[issue_type].append(issue)
    
    for issue_type, type_issues in by_type.items():
        icon = "🐛" if issue_type == "BUG" else "🔒" if issue_type == "VULNERABILITY" else "💩"
        description += f"\n**{icon} {issue_type}s ({len(type_issues)})**\n"
        for issue in type_issues[:5]:  # Show first 5
            description += f"- {issue.get('message', 'No message')}\n"
        if len(type_issues) > 5:
            description += f"- ... and {len(type_issues) - 5} more\n"
    
    description += f"\n---\n*Generated by CI/CD Quality Assistant*\n*Session: `{session_id}`*"
    
    # For demo, create a simple MR
    # In production, you'd generate actual code fixes
    changes = {
        ".sonarqube-fixes": f"# Quality Fixes Applied\n\nFixed {len(issues)} issues\n"
    }
    
    branch_name = f"quality-fixes/{session_id[:8]}"
    
    result = await create_merge_request(
        title=f"Fix {len(issues)} SonarQube issues",
        description=description,
        changes=changes,
        source_branch=branch_name,
        target_branch="main",
        project_id=project_id
    )
    
    return result

@tool
async def get_all_project_issues(
    project_key: str,
    resolved: bool = False
) -> List[Dict[str, Any]]:
    """Get all issues for a project
    
    Args:
        project_key: SonarQube project key
        resolved: Include resolved issues
    
    Returns:
        List of all project issues
    """
    # Fetch all issue types
    all_issues = []
    
    # Get bugs
    bugs = await get_code_quality_issues(
        severity=None,
        issue_type="BUG",
        project_id=project_key
    )
    all_issues.extend(bugs)
    
    # Get vulnerabilities
    vulnerabilities = await get_code_quality_issues(
        severity=None,
        issue_type="VULNERABILITY",
        project_id=project_key
    )
    all_issues.extend(vulnerabilities)
    
    # Get code smells
    code_smells = await get_code_quality_issues(
        severity=None,
        issue_type="CODE_SMELL",
        project_id=project_key
    )
    all_issues.extend(code_smells)
    
    logger.info(f"Found {len(all_issues)} total issues for project {project_key}")
    
    return all_issues

@tool
async def get_issue_details(
    issue_key: str
) -> Dict[str, Any]:
    """Get detailed information about a specific issue
    
    Args:
        issue_key: SonarQube issue key
    
    Returns:
        Detailed issue information
    """
    # In production, this would call SonarQube API
    # For now, return mock details
    return {
        "key": issue_key,
        "message": "Detailed issue information",
        "component": "src/main/java/Example.java",
        "line": 42,
        "textRange": {
            "startLine": 42,
            "endLine": 45
        },
        "flows": [],
        "resolution": None,
        "status": "OPEN"
    }

def _parse_effort(effort_str: str) -> int:
    """Parse effort string to minutes"""
    if not effort_str:
        return 0
    
    # Handle formats like "10min", "2h", "1d"
    effort_str = effort_str.lower().strip()
    
    if "d" in effort_str:
        days = int(effort_str.replace("d", "").strip() or 0)
        return days * 480  # 8 hours per day
    elif "h" in effort_str:
        hours = int(effort_str.replace("h", "").strip() or 0)
        return hours * 60
    elif "min" in effort_str:
        return int(effort_str.replace("min", "").strip() or 0)
    
    return 0