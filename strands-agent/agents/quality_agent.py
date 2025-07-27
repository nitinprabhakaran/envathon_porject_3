"""SonarQube quality analysis agent"""
from typing import Dict, Any, List
from datetime import datetime
from strands import Agent
from strands.models import BedrockModel, AnthropicModel
from utils.logger import log
from config import settings
from tools.sonarqube import (
    get_project_quality_gate_status,
    get_project_issues,
    get_project_metrics,
    get_issue_details,
    get_rule_description
)
from tools.gitlab import (
    get_file_content,
    create_merge_request,
    get_project_info
)

QUALITY_SYSTEM_PROMPT = """You are an expert code quality analyst specialized in SonarQube quality gate failures.

## Your Role
Analyze quality issues and provide actionable fixes. Every analysis must include:
1. A summary of quality issues by category
2. Specific fixes for each issue
3. Confidence score for proposed fixes

## Analysis Format
Use this exact format for your responses:

### 🔍 Quality Analysis
**Confidence**: [0-100]%
**Quality Gate Status**: [ERROR/WARN/OK]
**Total Issues**: [count]

### 📊 Issue Breakdown
- 🐛 **Bugs**: [count] issues
- 🔒 **Vulnerabilities**: [count] issues  
- 💩 **Code Smells**: [count] issues

### 📋 Detailed Findings
[List top issues by severity with file locations]

### 💡 Proposed Fixes
[For each file with issues:]
**File**: `path/to/file.ext`
```language
[Show the fixed code]
```

### ⚡ Quick Actions
- [ ] Fix critical bugs first
- [ ] Address security vulnerabilities
- [ ] Clean up code smells
- [ ] Create MR: [Yes/No - only if you have all fixes ready]

## Important Guidelines
- NEVER create a merge request without explicit user permission
- Prioritize security vulnerabilities and bugs over code smells
- Show complete fixed code, not just descriptions
- Branch names should be: sonarqube_agent_fix_[timestamp]
- Group similar issues together for batch fixing"""

class QualityAgent:
    def __init__(self):
        # Initialize LLM based on provider
        if settings.llm_provider == "bedrock":
            self.model = BedrockModel(
                region=settings.aws_region,
                access_key_id=settings.aws_access_key_id,
                secret_access_key=settings.aws_secret_access_key
            )
        else:
            self.model = AnthropicModel(
                api_key=settings.anthropic_api_key
            )
        
        # Initialize agent with tools
        self.agent = Agent(
            model=self.model,
            system_prompt=QUALITY_SYSTEM_PROMPT,
            tools=[
                get_project_quality_gate_status,
                get_project_issues,
                get_project_metrics,
                get_issue_details,
                get_rule_description,
                get_file_content,
                create_merge_request,
                get_project_info
            ]
        )
        log.info("Quality agent initialized")
    
    async def analyze_quality_issues(
        self,
        session_id: str,
        project_key: str,
        gitlab_project_id: str,
        webhook_data: Dict[str, Any]
    ) -> str:
        """Analyze quality gate failure and return findings"""
        log.info(f"Analyzing quality issues for {project_key} in session {session_id}")
        
        prompt = f"""Analyze this SonarQube quality gate failure:

SonarQube Project Key: {project_key}
GitLab Project ID: {gitlab_project_id}
Quality Gate Status: {webhook_data.get('qualityGate', {}).get('status', 'ERROR')}

Use the available tools to:
1. Get the quality gate status and failed conditions
2. Get all project issues (bugs, vulnerabilities, code smells)
3. For each issue type, get the file content from GitLab
4. Analyze the issues and provide fixes
5. Present findings in the specified format

Important: 
- Use project_key="{project_key}" for SonarQube API calls
- Use project_id="{gitlab_project_id}" for GitLab API calls
- Do NOT create a merge request, only analyze and propose fixes"""
        
        response = await self.agent.run(prompt)
        log.info(f"Quality analysis complete for session {session_id}")
        return response
    
    async def handle_user_message(
        self,
        session_id: str,
        message: str,
        conversation_history: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> str:
        """Handle user message in conversation"""
        log.info(f"Handling user message for quality session {session_id}")
        
        # Add conversation context
        self.agent.conversation_history = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in conversation_history
        ]
        
        # Check if user wants to create MR
        if "create" in message.lower() and ("mr" in message.lower() or "merge request" in message.lower()):
            # Generate branch name
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            branch_name = f"sonarqube_agent_fix_{timestamp}"
            
            prompt = f"""The user wants to create a merge request with the quality fixes.

GitLab Project ID: {context['gitlab_project_id']}
Branch Name: {branch_name}

Based on our previous analysis, create a merge request with all the fixes for the quality issues.
Use the create_merge_request tool with the exact file changes we discussed."""
        else:
            prompt = message
        
        response = await self.agent.run(prompt)
        log.debug(f"Generated quality response for session {session_id}")
        return response