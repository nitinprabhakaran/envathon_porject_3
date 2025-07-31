"""SonarQube quality analysis agent"""
from typing import Dict, Any, List, Optional
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

## Important Rules for File Access
- When you need to fix issues in specific files, ALWAYS attempt to retrieve the file content using get_file_content()
- If get_file_content() returns an error or fails, acknowledge this and explain that you cannot provide specific fixes without access to the source code
- NEVER create a merge request if you cannot access the files that need to be changed
- When creating MRs, only include files that you have successfully retrieved and can actually modify

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
- If file can be retrieved, show the fixed code
- If file cannot be retrieved, explain the issue and suggested fix approach

### ⚡ Quick Actions
- [ ] Fix critical bugs first
- [ ] Address security vulnerabilities
- [ ] Clean up code smells
- [ ] Create MR: [Only "Yes" if you have actual file content and fixes ready]

## Guidelines for MR Creation
- Only create MR if you have successfully retrieved and modified at least one file
- If asked to create MR but cannot access files, explain why and suggest manual fixes
- Always verify file content exists before including in MR
- Branch names should be: fix/sonarqube_[timestamp]
- When creating MR, ALWAYS include the full MR URL in your response"""

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
        
        # Check if issues are already fetched
        total_issues = 0
        if 'quality_metrics' in webhook_data:
            metrics = webhook_data['quality_metrics']
            total_issues = metrics.get('total_issues', 0)
        
        prompt = f"""Analyze this SonarQube quality gate failure:

SonarQube Project Key: {project_key}
GitLab Project ID: {gitlab_project_id}
Quality Gate Status: {webhook_data.get('qualityGate', {}).get('status', 'ERROR')}

Failed Conditions:
{webhook_data.get('qualityGate', {}).get('conditions', [])}

Use the available tools to:
1. Get the project metrics using get_project_metrics()
2. Get all project issues using get_project_issues() - separate calls for BUG, VULNERABILITY, CODE_SMELL
3. For the top issues, attempt to get the file content from GitLab using get_file_content()
4. If you can retrieve files, analyze the issues and provide specific fixes
5. If you cannot retrieve files, explain the issues conceptually and provide general guidance
6. Present findings in the specified format with ACTUAL metrics

Important: 
- Use project_key="{project_key}" for SonarQube API calls
- Use project_id="{gitlab_project_id}" for GitLab API calls
- If files cannot be retrieved, acknowledge this and provide conceptual fixes
- Do NOT create a merge request unless you have actual file content to work with"""
        
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
1. First, verify which files need to be changed based on the previous analysis
2. Attempt to retrieve each file using get_file_content()
3. If you can retrieve files:
   - Apply the fixes to the actual file content
   - Use create_merge_request with the modified files
   - Include the complete MR URL in your response
4. If you CANNOT retrieve files:
   - Explain that you cannot access the source files
   - List which files would need to be changed
   - Provide manual instructions for the fixes
   - DO NOT create an empty merge request

Use these parameters IF creating MR:
- GitLab Project ID: {context.gitlab_project_id}
- Source Branch: {branch_name}
- Target Branch: main
- Title: Fix SonarQube quality gate failures
- Description: Automated fixes for bugs, vulnerabilities, and code smells

Remember: Only create an MR if you have actual file content to commit."""
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