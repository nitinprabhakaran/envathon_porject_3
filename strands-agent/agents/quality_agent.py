"""SonarQube quality analysis agent"""
from typing import Dict, Any, List
from datetime import datetime
from strands import Agent
import os
from strands.models.bedrock import BedrockModel
from strands.models.anthropic import AnthropicModel
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
                model_id=os.getenv("MODEL_ID", "us.anthropic.claude-3-5-sonnet-20241022-v2:0"),
                region=os.getenv("AWS_REGION", "us-west-2"),
                temperature=0.3,
                streaming=True,
                max_tokens=4096,
                top_p=0.8
            )
        else:
            self.model = AnthropicModel(
                model_id=os.getenv("MODEL_ID", "claude-3-5-sonnet-20241022"),
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                temperature=0.3,
                max_tokens=4096
            )
        
        # Store tools for reuse
        self.tools = [
            get_project_quality_gate_status,
            get_project_issues,
            get_project_metrics,
            get_issue_details,
            get_rule_description,
            get_file_content,
            create_merge_request,
            get_project_info
        ]
        
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
        
        # Create fresh agent for analysis
        agent = Agent(
            model=self.model,
            system_prompt=QUALITY_SYSTEM_PROMPT,
            tools=self.tools
        )
        
        result = await agent.invoke_async(prompt)
        log.info(f"Quality analysis complete for session {session_id}")
        
        # Extract text from result
        if hasattr(result, 'message'):
            return result.message
        return str(result)
    
    async def handle_user_message(
        self,
        session_id: str,
        message: str,
        conversation_history: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> str:
        """Handle user message in conversation"""
        log.info(f"Handling user message for quality session {session_id}")
        
        # Prepare context from conversation history
        context_text = ""
        for msg in conversation_history:
            if msg["role"] == "system":
                context_text += f"{msg['content']}\n"
            elif msg["role"] == "assistant" and msg["content"]:
                context_text += f"Previous analysis:\n{msg['content']}\n"
        
        # Build final prompt with context
        if "create" in message.lower() and ("mr" in message.lower() or "merge request" in message.lower()):
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            branch_name = f"sonarqube_agent_fix_{timestamp}"
            
            final_prompt = f"""{context_text}

The user wants to create a merge request with the quality fixes.

GitLab Project ID: {context['gitlab_project_id']}
Branch Name: {branch_name}

Based on the previous analysis, create a merge request with all the fixes for the quality issues.
Use the create_merge_request tool with the exact file changes discussed."""
        else:
            final_prompt = f"{context_text}\n{message}" if context_text else message
        
        # Create fresh agent and invoke
        agent = Agent(
            model=self.model,
            system_prompt=QUALITY_SYSTEM_PROMPT,
            tools=self.tools
        )
        
        result = await agent.invoke_async(final_prompt)
        log.debug(f"Generated response for session {session_id}")
        
        # Return the message directly
        return result.message