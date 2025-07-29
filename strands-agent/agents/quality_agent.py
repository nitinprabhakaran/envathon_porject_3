"""SonarQube quality analysis agent"""
from typing import Dict, Any, List
from datetime import datetime
from strands import Agent
import os
from strands.models.bedrock import BedrockModel
from strands.models.anthropic import AnthropicModel
from utils.logger import log
from config import settings
from db.models import SessionContext
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
Analyze quality issues and provide actionable fixes. When analyzing, always fetch the actual metrics first.

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
```language
[Show the fixed code]
```

### ⚡ Quick Actions
- [ ] Fix critical bugs first
- [ ] Address security vulnerabilities
- [ ] Clean up code smells
- [ ] Create MR: [Yes/No - only if you have all fixes ready]

## Important Guidelines
- Always use get_project_metrics() and get_project_issues() tools first
- Show actual numbers, not placeholders
- NEVER create a merge request without explicit user permission
- Prioritize security vulnerabilities and bugs over code smells
- Show complete fixed code, not just descriptions
- Branch names should be: fix/sonarqube_[timestamp]
- When creating MR, ALWAYS include the full MR URL in your response
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

Failed Conditions:
{webhook_data.get('qualityGate', {}).get('conditions', [])}

Use the available tools to:
1. Get the project metrics using get_project_metrics()
2. Get all project issues using get_project_issues() - separate calls for BUG, VULNERABILITY, CODE_SMELL
3. For the top issues, get the file content from GitLab
4. Analyze the issues and provide fixes
5. Present findings in the specified format with ACTUAL metrics

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
        context: SessionContext
    ) -> str:
        """Handle user message in conversation"""
        log.info(f"Handling user message for quality session {session_id}")
        
        # Check for MR creation request
        is_mr_request = "create" in message.lower() and ("mr" in message.lower() or "merge request" in message.lower())
        
        # Build context prompt
        context_prompt = f"""
Session Context:
- Project: {context.project_name}
- SonarQube Key: {context.sonarqube_key}
- GitLab Project ID: {context.gitlab_project_id}
- Quality Gate Status: {context.quality_gate_status}
"""
        
        # Add conversation summary (last analysis)
        if conversation_history:
            for msg in reversed(conversation_history):
                if msg["role"] == "assistant" and "Proposed Fixes" in msg.get("content", ""):
                    context_prompt += f"\n\nPrevious Analysis:\n{msg['content']}"
                    break
        
        # Prepare final prompt
        if is_mr_request:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            branch_name = f"fix/sonarqube_{timestamp}"
            
            final_prompt = f"""{context_prompt}

The user wants to create a merge request with the quality fixes.

CRITICAL INSTRUCTIONS:
1. Use the create_merge_request tool with all the file changes from the previous analysis
2. After creating the MR, you MUST include the complete MR URL in your response
3. Format your response to clearly show:
   - How many issues were fixed
   - What files were changed
   - The branch name created
   - **The full merge request URL** (e.g., https://gitlab.example.com/group/project/-/merge_requests/123)

Use these parameters:
- GitLab Project ID: {context.gitlab_project_id}
- Source Branch: {branch_name}
- Target Branch: main
- Title: Fix SonarQube quality gate failures
- Description: Automated fixes for bugs, vulnerabilities, and code smells

Create the merge request now with all the fixes."""
        else:
            final_prompt = f"{context_prompt}\n\nUser Question: {message}"
        
        # Create fresh agent and invoke
        agent = Agent(
            model=self.model,
            system_prompt=QUALITY_SYSTEM_PROMPT,
            tools=self.tools
        )
        
        result = await agent.invoke_async(final_prompt)
        log.debug(f"Generated response for session {session_id}")
        
        # Return the message directly
        return result.message if hasattr(result, 'message') else str(result)