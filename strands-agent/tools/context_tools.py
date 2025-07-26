import os
import yaml
from typing import Dict, Any, List, Optional
from strands import tool
from loguru import logger

from .gitlab_tools import get_file_content
from vector.qdrant_client import QdrantManager

@tool
async def get_relevant_code_context(
    error_signature: str,
    project_id: Optional[str] = None,
    expand_scope: bool = False
) -> Dict[str, Any]:
    """Retrieve code sections most likely related to the error
    
    Args:
        error_signature: The error signature to search for
        project_id: The project ID
        expand_scope: Whether to expand search scope
    
    Returns:
        Relevant code sections and files
    """
    if not project_id:
        # Try to get from context
        project_id = "default"
    
    qdrant = QdrantManager()
    
    # Search for relevant code
    results = await qdrant.search_code_context(
        project_id=project_id,
        query=error_signature,
        limit=10 if expand_scope else 5
    )
    
    return {
        "error_signature": error_signature,
        "relevant_files": [r["file_path"] for r in results if "file_path" in r],
        "code_sections": results,
        "expanded_scope": expand_scope,
        "total_results": len(results)
    }

@tool
async def request_additional_context(
    context_type: str,
    scope: str = "project",
    specific_files: Optional[List[str]] = None,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Request additional context when current information is insufficient
    
    Args:
        context_type: Type of context needed (dependencies, test_files, config_files, etc.)
        scope: Scope of context (project, directory, file)
        specific_files: List of specific files to retrieve
        project_id: The project ID
    
    Returns:
        Retrieved context information
    """
    context_data = {
        "context_type": context_type,
        "scope": scope,
        "files_retrieved": []
    }
    
    if context_type == "dependencies":
        # Common dependency files
        dependency_files = [
            "package.json", "package-lock.json",  # Node.js
            "requirements.txt", "Pipfile", "pyproject.toml",  # Python
            "Gemfile", "Gemfile.lock",  # Ruby
            "go.mod", "go.sum",  # Go
            "pom.xml", "build.gradle",  # Java
            "Cargo.toml", "Cargo.lock"  # Rust
        ]
        
        for file in dependency_files:
            try:
                content = await get_file_content(file, "HEAD", project_id)
                if not content.startswith("Error:"):
                    context_data["files_retrieved"].append({
                        "file": file,
                        "type": "dependency",
                        "content": content
                    })
            except Exception as e:
                logger.debug(f"File {file} not found: {e}")
    
    elif context_type == "config_files":
        # Common configuration files
        config_files = [
            ".gitlab-ci.yml",
            "Dockerfile", "docker-compose.yml",
            ".env.example", "config.yml", "config.json",
            "tsconfig.json", "webpack.config.js",
            "setup.py", "setup.cfg"
        ]
        
        for file in config_files:
            try:
                content = await get_file_content(file, "HEAD", project_id)
                if not content.startswith("Error:"):
                    context_data["files_retrieved"].append({
                        "file": file,
                        "type": "config",
                        "content": content
                    })
            except Exception as e:
                logger.debug(f"File {file} not found: {e}")
    
    elif context_type == "test_files":
        # Look for test directories
        test_patterns = [
            "tests/", "test/", "__tests__/", "spec/",
            "test_*.py", "*_test.py", "*.test.js", "*.spec.js"
        ]
        # This is simplified - in production, use GitLab API to list files
        context_data["note"] = "Test file discovery requires repository file listing"
    
    elif context_type == "specific" and specific_files:
        for file_path in specific_files:
            try:
                content = await get_file_content(file_path, "HEAD", project_id)
                if not content.startswith("Error:"):
                    context_data["files_retrieved"].append({
                        "file": file_path,
                        "type": "specific",
                        "content": content
                    })
            except Exception as e:
                logger.error(f"Failed to get {file_path}: {e}")
    
    return context_data

@tool
async def get_shared_pipeline_context(
    template_ref: Optional[str] = None,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieve shared pipeline templates and their context
    
    Args:
        template_ref: Reference to template (if known)
        project_id: The project ID
    
    Returns:
        Shared pipeline templates and variables
    """
    # Get main CI file
    ci_content = await get_file_content(".gitlab-ci.yml", "HEAD", project_id)
    
    if ci_content.startswith("Error:"):
        return {
            "error": "Could not retrieve .gitlab-ci.yml",
            "details": ci_content
        }
    
    shared_context = {
        "main_ci_file": ci_content,
        "includes": [],
        "variables": {},
        "stages": [],
        "jobs": []
    }
    
    try:
        # Parse YAML
        ci_config = yaml.safe_load(ci_content)
        
        # Extract includes
        includes = ci_config.get("include", [])
        if isinstance(includes, list):
            for include in includes:
                if isinstance(include, dict):
                    shared_context["includes"].append(include)
                    
                    # Try to fetch included template
                    if "project" in include and "file" in include:
                        try:
                            # This would need proper project ID resolution
                            template_content = await get_file_content(
                                include["file"],
                                include.get("ref", "main"),
                                include["project"]
                            )
                            if not template_content.startswith("Error:"):
                                shared_context["includes"][-1]["content"] = template_content
                        except Exception as e:
                            logger.debug(f"Could not fetch template: {e}")
        
        # Extract variables
        shared_context["variables"] = ci_config.get("variables", {})
        
        # Extract stages
        shared_context["stages"] = ci_config.get("stages", [])
        
        # Extract job names
        for key, value in ci_config.items():
            if isinstance(value, dict) and key not in ["variables", "stages", "include", "default"]:
                shared_context["jobs"].append({
                    "name": key,
                    "stage": value.get("stage", "test"),
                    "extends": value.get("extends", [])
                })
        
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse CI YAML: {e}")
        shared_context["parse_error"] = str(e)
    
    return shared_context

@tool
async def trace_pipeline_inheritance(
    ci_file_path: str = ".gitlab-ci.yml",
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Follow include/extends chains to map full pipeline context
    
    Args:
        ci_file_path: Path to CI file
        project_id: The project ID
    
    Returns:
        Pipeline inheritance map
    """
    # Get the CI file
    ci_content = await get_file_content(ci_file_path, "HEAD", project_id)
    
    if ci_content.startswith("Error:"):
        return {
            "error": "Could not retrieve CI file",
            "details": ci_content
        }
    
    inheritance_map = {
        "base_file": ci_file_path,
        "includes": [],
        "extends_chain": {},
        "variables_chain": {},
        "template_hierarchy": []
    }
    
    try:
        ci_config = yaml.safe_load(ci_content)
        
        # Process includes
        includes = ci_config.get("include", [])
        if isinstance(includes, list):
            for include in includes:
                if isinstance(include, dict):
                    inheritance_map["includes"].append({
                        "type": "remote" if "remote" in include else "project" if "project" in include else "local",
                        "source": include
                    })
        elif isinstance(includes, str):
            inheritance_map["includes"].append({
                "type": "local",
                "source": includes
            })
        
        # Process job inheritance (extends)
        for job_name, job_config in ci_config.items():
            if isinstance(job_config, dict) and "extends" in job_config:
                extends = job_config["extends"]
                if isinstance(extends, str):
                    extends = [extends]
                inheritance_map["extends_chain"][job_name] = extends
        
        # Trace variable inheritance
        base_vars = ci_config.get("variables", {})
        inheritance_map["variables_chain"]["base"] = base_vars
        
        # Build hierarchy
        inheritance_map["template_hierarchy"] = [
            {
                "level": 0,
                "type": "base",
                "file": ci_file_path,
                "has_includes": len(inheritance_map["includes"]) > 0,
                "job_count": len([k for k in ci_config.keys() if isinstance(ci_config[k], dict) and k not in ["variables", "stages", "include"]])
            }
        ]
        
    except yaml.YAMLError as e:
        inheritance_map["parse_error"] = str(e)
    
    return inheritance_map

@tool
async def get_cicd_variables(
    security_level: str = "pipeline",
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieve CI/CD variables based on security clearance
    
    Args:
        security_level: Level of variables to retrieve (pipeline, project, all)
        project_id: The project ID
    
    Returns:
        Available CI/CD variables at requested level
    """
    variables = {
        "pipeline_level": {},
        "project_level": {},
        "group_level": {},
        "masked_count": 0,
        "total_count": 0
    }
    
    # Get CI file to extract pipeline-level variables
    if security_level in ["pipeline", "all"]:
        ci_content = await get_file_content(".gitlab-ci.yml", "HEAD", project_id)
        
        if not ci_content.startswith("Error:"):
            try:
                ci_config = yaml.safe_load(ci_content)
                pipeline_vars = ci_config.get("variables", {})
                variables["pipeline_level"] = pipeline_vars
                variables["total_count"] += len(pipeline_vars)
            except yaml.YAMLError:
                logger.error("Failed to parse CI YAML for variables")
    
    # Note: Project and group level variables would require GitLab API access
    # with proper permissions. For now, we indicate what would be available
    
    if security_level in ["project", "all"]:
        variables["project_level"]["_note"] = "Project variables require GitLab API access"
        # In production, you would call GitLab API to get project variables
    
    if security_level == "all":
        variables["group_level"]["_note"] = "Group variables require GitLab API access"
        # In production, you would call GitLab API to get group variables
    
    # Add common CI/CD predefined variables that are always available
    variables["predefined"] = {
        "CI": "true",
        "CI_PROJECT_ID": project_id or "unknown",
        "CI_PIPELINE_SOURCE": "push",
        "CI_COMMIT_REF_NAME": "main",
        "CI_DEFAULT_BRANCH": "main",
        "GITLAB_CI": "true"
    }
    
    return variables