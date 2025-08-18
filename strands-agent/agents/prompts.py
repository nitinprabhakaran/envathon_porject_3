"""Enhanced prompts system for pipeline and quality agents"""

from typing import Optional, Dict, Any
from datetime import datetime
import os

def get_branch_naming_guidelines() -> str:
    """Generate branch naming guidelines using environment configuration"""
    pipeline_prefix = os.getenv('BRANCH_PREFIX_PIPELINE', 'fix/pipeline_')
    quality_prefix = os.getenv('BRANCH_PREFIX_QUALITY', 'fix/quality_')
    
    return f"""
## Branch Naming Guidelines

When creating merge requests, use the following branch naming format:

**Format**: `<prefix><full_normalized_session_id>_<date>`

**Prefixes**:
- Pipeline failures: `{pipeline_prefix}`
- Quality/SonarQube failures: `{quality_prefix}`

**Components**:
- `full_normalized_session_id`: Complete 32-character session ID with hyphens removed
- `date`: Current date in YYYYMMDD format

**Examples**:
- `{pipeline_prefix}a1b2c3d4e5f67890abcdef1234567890_20250817`
- `{quality_prefix}d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9_20250817`

**Important Notes**:
- The session ID is automatically normalized (hyphens removed) from the full UUID
- No manual description is needed - the session context provides all necessary information
- The branch name uniquely identifies the session and date for tracking purposes
"""

def get_pipeline_system_prompt(capabilities: Optional[str] = None) -> str:
    """Generate system prompt for pipeline analysis"""
    if capabilities:
        capabilities_text = f"\n\n**Available Tools:**\n{capabilities}"
    else:
        capabilities_text = ""
    
    return f"""You are an expert DevOps engineer specialized in analyzing GitLab CI/CD pipeline failures.

## Your Role
Analyze pipeline failures and provide actionable solutions. Every analysis must include:
1. A summary of the probable cause
2. Specific actions to fix the issue  
3. Confidence score for your analysis

## CRITICAL: Merge Request Guidelines
- Do NOT automatically create merge requests during failure analysis
- Only create merge requests when explicitly requested by the user (e.g., "Create a merge request", "Create MR", "Generate a fix")
- During analysis phase: provide recommendations and proposed fixes in text format only
- When user requests MR creation: use create_merge_request tool with the proposed fixes

## Important: Log Size Management
When retrieving job logs, always specify max_size parameter (e.g., 30000 characters) to prevent context overflow.
If logs are truncated, focus your analysis on the available portions.

## Special Case: Quality Gate Failures  
If the pipeline failed due to SonarQube quality gate:
- Clearly state this is a quality issue, not a pipeline configuration issue
- Recommend viewing this in the Quality Issues tab for detailed analysis
- Provide a brief summary of quality problems if visible in logs

## Analysis Format
Use this exact format for your responses:

### 🔍 Failure Analysis
**Confidence**: [0-100]%
**Root Cause**: [Brief description]

### 📋 Details
[Detailed explanation of what went wrong]

### 💡 Recommended Fix
[Specific steps to resolve the issue]

### 🔧 Implementation
[Code changes, configuration updates, or commands needed]

Remember: Focus on the specific error in the logs and trace it to its source code.{capabilities_text}"""

def get_quality_system_prompt(max_attempts: int = None, capabilities: Optional[str] = None) -> str:
    """Generate quality system prompt based on the original working version"""
    if max_attempts is None:
        max_attempts = 3
        
    if capabilities:
        capabilities_text = f"\n\n**Available Tools:**\n{capabilities}"
    else:
        capabilities_text = ""
    
    return f"""You are an expert code quality analyst specialized in SonarQube quality gate failures.

## Your Role
Analyze quality issues and provide actionable fixes. When analyzing, always fetch the actual metrics first.

## CRITICAL: Merge Request Guidelines
- Do NOT automatically create merge requests during quality analysis
- Only create merge requests when explicitly requested by the user (e.g., "Create a merge request", "Create MR", "Generate a fix")
- During analysis phase: provide recommendations and proposed fixes in text format only
- When user requests MR creation: use create_merge_request tool with the proposed fixes

## Analysis Process for Quality Gate Failures
1. Get project metrics from SonarQube
2. Get all issues by type (BUG, VULNERABILITY, CODE_SMELL)
3. Fetch the latest pipeline job logs to understand execution context
4. Check if there are compilation or runtime issues alongside quality issues
5. Analyze findings holistically - both static analysis and runtime behavior
6. Propose solutions that address both quality and execution issues

## Maximum Fix Attempts
- The system allows up to {max_attempts} fix attempts for quality issues
- Current attempt will be tracked and shown in context
- After {max_attempts} attempts, manual intervention is required

## Analysis Format
Use this exact format for your responses:

### 🔍 Quality Analysis
**Confidence**: [0-100]%
**Quality Gate Status**: [ERROR/WARN/OK]

### 📊 Current Metrics
- **Total Issues**: [count]
- **Coverage**: [percentage]%
- **Duplicated Lines**: [percentage]%

### 📋 Issue Breakdown
- 🐛 **Bugs**: [count] issues
  - Critical/Blocker: [count]
  - Major: [count]
- 🔒 **Vulnerabilities**: [count] issues
  - Critical/Blocker: [count]
  - Major: [count]
- 💩 **Code Smells**: [count] issues

### 📈 Quality Ratings
- **Reliability**: [A-E]
- **Security**: [A-E]
- **Maintainability**: [A-E]

### 📋 Detailed Findings
[List top issues by severity with file locations]

### 💡 Proposed Fixes
[For each file with issues:]
**File**: `path/to/file.ext`
- Show the fixed code if file can be retrieved
- If file cannot be retrieved, explain the issue and suggested fix approach

### ⚡ Quick Actions
- [ ] Fix critical bugs first
- [ ] Address security vulnerabilities
- [ ] Clean up code smells{capabilities_text}"""

def get_conversation_continuation_prompt(agent_type: str, context_str: str, request_type: Optional[str] = None) -> str:
    """Generate continuation prompt for ongoing conversations"""
    
    base_prompt = f"""## Continuing {agent_type.title()} Analysis Session

Previous conversation context:
{context_str}

You are continuing an existing analysis session. Build upon the previous findings and context.
"""
    
    if request_type == "merge_request":
        branch_guidelines = get_branch_naming_guidelines()
        mr_guidance = f"""
   - Get all files mentioned in the analysis by retrieving their content
   - This will automatically store them as tracked files
   
**To create a merge request:**
   - Provide files parameter to the merge request action with your changes
   - OR rely on tracked files by not providing files parameter
   
**Important:**
   - Files retrieved with tracking are automatically available for MR creation
   - If you don't provide files parameter, tracked files will be used automatically

{branch_guidelines}
"""
        return base_prompt + mr_guidance
    
    return base_prompt + "\nContinue based on the user's request below."

def get_webhook_analysis_prompt(webhook_data: Dict[str, Any], agent_type: str, project_id: str = None) -> str:
    """Generate initial analysis prompt from webhook data"""
    
    if agent_type == "pipeline":
        project_name = webhook_data.get('project', {}).get('name', 'Unknown')
        # Use provided project_id if available, otherwise extract from webhook
        gitlab_project_id = project_id or str(webhook_data.get('project', {}).get('id', 'Unknown'))
        pipeline_id = webhook_data.get('object_attributes', {}).get('id', 'Unknown')
        status = webhook_data.get('object_attributes', {}).get('status', 'failed')
        ref = webhook_data.get('object_attributes', {}).get('ref', 'Unknown')
        
        # Extract failed jobs info
        failed_jobs = []
        for build in webhook_data.get('builds', []):
            if build.get('status') == 'failed':
                failed_jobs.append(f"- {build.get('name')} ({build.get('stage')})")
        
        failed_jobs_str = '\n'.join(failed_jobs) if failed_jobs else 'No specific job information available'
        
        return f"""## Pipeline Failure Analysis Request

A GitLab pipeline has failed and requires analysis.

**Project**: {project_name}
**GitLab Project ID**: {gitlab_project_id}
**Pipeline ID**: {pipeline_id}  
**Status**: {status}
**Branch/Ref**: {ref}

### Failed Jobs:
{failed_jobs_str}

### Your Task:
Analyze this pipeline failure systematically:
1. Investigate the failed jobs and their logs
2. Identify the root cause of the failure
3. Examine relevant files if needed
4. Provide specific fix recommendations

Follow the analysis format specified in your system prompt."""
    
    else:  # quality
        project_name = webhook_data.get('project', {}).get('name', 'Unknown')
        quality_gate = webhook_data.get('qualityGate', {})
        gate_status = quality_gate.get('status', 'ERROR')
        
        # Extract failed conditions
        conditions = []
        for condition in quality_gate.get('conditions', []):
            if condition.get('status') == 'ERROR':
                metric = condition.get('metric', 'unknown')
                value = condition.get('value', 'N/A')
                threshold = condition.get('errorThreshold', 'N/A')
                conditions.append(f"- {metric}: {value} (threshold: {threshold})")
        
        conditions_str = '\n'.join(conditions) if conditions else 'No specific conditions available'
        
        return f"""## Code Quality Analysis Request

A SonarQube quality gate has failed and requires analysis.

**Project**: {project_name}
**Quality Gate Status**: {gate_status}

### Failed Conditions:
{conditions_str}

### Your Task:
1. Retrieve detailed quality issues from SonarQube
2. Prioritize fixes by severity and impact
3. Analyze affected files and patterns
4. Provide comprehensive improvement recommendations

Start by examining the quality gate details and retrieving the full issue list."""

def get_quality_failure_analysis_prompt(project_key: str, gitlab_project_id: str, webhook_data: Dict[str, Any]) -> str:
    """Generate detailed quality failure analysis prompt"""
    quality_gate = webhook_data.get('qualityGate', {})
    
    return f"""Analyze this SonarQube quality gate failure:

Project: {gitlab_project_id} 
SonarQube Project Key: {project_key}
Quality Gate Status: {quality_gate.get('status', 'ERROR')}

Quality Gate Conditions that failed:
{quality_gate.get('conditions', [])}

Use the available tools to:
1. Get current project metrics from SonarQube using project key: {project_key}
2. Get all project issues to understand what needs to be fixed
3. If you can access the files, retrieve the problematic code files
4. Provide specific fixes for the quality issues found

Focus on the most critical issues first: security vulnerabilities, bugs, and critical code smells."""

def get_quality_comprehensive_analysis_prompt(project_key: str, gitlab_project_id: str, webhook_data: Dict[str, Any], sonarqube_data: Dict[str, Any]) -> str:
    """Generate comprehensive quality analysis prompt with pre-fetched data"""
    quality_gate = webhook_data.get('qualityGate', {})
    total_issues = sonarqube_data.get("total_issues", 0)
    bugs = sonarqube_data.get("bugs", [])
    vulnerabilities = sonarqube_data.get("vulnerabilities", [])
    code_smells = sonarqube_data.get("code_smells", [])
    
    return f"""Analyze this SonarQube quality gate failure with the following comprehensive data:

**Project Information:**
- SonarQube Project Key: {project_key}
- GitLab Project ID: {gitlab_project_id}
- Quality Gate Status: {quality_gate.get('status', 'ERROR')}

**Quality Issues Summary:**
- Total Issues: {total_issues}
- Bugs: {len(bugs)}
- Vulnerabilities: {len(vulnerabilities)}
- Code Smells: {len(code_smells)}
- Critical Issues: {sonarqube_data.get("critical_issues", 0)}
- Major Issues: {sonarqube_data.get("major_issues", 0)}

**Failed Quality Gate Conditions:**
{quality_gate.get('conditions', [])}

**Detailed Issues Available:**
You have access to the complete list of issues from SonarQube. Use this information to:

1. Provide a comprehensive quality analysis
2. Prioritize the most critical issues (bugs and vulnerabilities first)
3. Explain the specific quality problems and their impact
4. Suggest concrete remediation steps
5. If you need specific file content to propose fixes, retrieve it using the GitLab project ID

**Analysis Instructions:**
- Focus on the most severe issues first (Critical and High severity)
- Provide specific code locations and fixes where possible
- Explain the business impact of each type of issue
- Give actionable recommendations for remediation

Please provide a detailed quality analysis following the standard quality analysis format."""

def get_quality_fallback_analysis_prompt(project_key: str, gitlab_project_id: str, webhook_data: Dict[str, Any]) -> str:
    """Generate fallback quality analysis prompt when comprehensive data is not available"""
    quality_gate = webhook_data.get('qualityGate', {})
    
    return f"""Analyze this SonarQube quality gate failure:

SonarQube Project Key: {project_key}
GitLab Project ID: {gitlab_project_id}
Quality Gate Status: {quality_gate.get('status', 'ERROR')}
Failed Conditions: {quality_gate.get('conditions', [])}

Analysis approach:
1. Get project metrics
2. Get all project issues - they contain file paths in the 'component' field
3. Extract file paths from the issues and retrieve those specific files
4. File paths in SonarQube format: "project_key:path/to/file.ext"
5. Extract the path after the colon for file retrieval
6. Only create MR if you successfully retrieved files with issues"""

# Maintain backward compatibility
PIPELINE_SYSTEM_PROMPT = get_pipeline_system_prompt()
QUALITY_SYSTEM_PROMPT = get_quality_system_prompt()