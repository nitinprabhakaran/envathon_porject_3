"""Pipeline failure analysis agent"""
from typing import Dict, Any, List
from datetime import datetime
from strands import Agent
import os
from strands.models.bedrock import BedrockModel
from strands.models.anthropic import AnthropicModel
from utils.logger import log
from config import settings
from tools.gitlab import (
    get_pipeline_jobs,
    get_job_logs,
    get_file_content,
    get_recent_commits,
    create_merge_request,
    get_project_info
)

PIPELINE_SYSTEM_PROMPT = """You are an expert DevOps engineer specialized in analyzing GitLab CI/CD pipeline failures.

## Your Role
Analyze pipeline failures and provide actionable solutions. Every analysis must include:
1. A summary of the probable cause
2. Specific actions to fix the issue
3. Confidence score for your analysis

## Analysis Format
Use this exact format for your responses:

### 🔍 Failure Analysis
**Confidence**: [0-100]%
**Root Cause**: [One sentence summary of the root cause]
**Error Type**: [dependency/build/test/deployment/configuration]

### 📋 Detailed Findings
[Detailed explanation of what went wrong and why]

### 💡 Proposed Solution
[Step-by-step solution to fix the issue]

### 🛠️ Required Changes
```
[Show exact file changes needed]
```

### ⚡ Quick Actions
- [ ] Action 1: [Specific action]
- [ ] Action 2: [Specific action]
- [ ] Create MR: [Yes/No - only if you have specific file changes]

## Important Guidelines
- NEVER create a merge request without explicit user permission
- Base confidence on clarity of error and certainty of fix
- If you need more information, ask specific questions
- Show actual code/config changes, not just descriptions
- Branch names should be: gitlab_agent_fix_[timestamp]"""

class PipelineAgent:
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
            get_pipeline_jobs,
            get_job_logs,
            get_file_content,
            get_recent_commits,
            create_merge_request,
            get_project_info
        ]
        
        log.info("Pipeline agent initialized")
    
    async def analyze_failure(
        self,
        session_id: str,
        project_id: str,
        pipeline_id: str,
        webhook_data: Dict[str, Any]
    ) -> str:
        """Analyze pipeline failure and return findings"""
        log.info(f"Analyzing pipeline {pipeline_id} failure for session {session_id}")
        
        # Extract failure info from webhook
        failed_jobs = [
            job for job in webhook_data.get("builds", [])
            if job.get("status") == "failed"
        ]
        
        if not failed_jobs:
            return "No failed jobs found in the pipeline."
        
        # Create analysis prompt
        failed_job = failed_jobs[0]  # Focus on first failure
        prompt = f"""Analyze this pipeline failure:

Project ID: {project_id}
Pipeline ID: {pipeline_id}
Failed Job: {failed_job.get('name', 'unknown')}
Stage: {failed_job.get('stage', 'unknown')}
Failure Reason: {failed_job.get('failure_reason', 'unknown')}

Use the available tools to:
1. Get the pipeline jobs and identify all failures
2. Get logs for the failed job(s)
3. Analyze the error and determine root cause
4. If needed, examine relevant files (CI config, dependencies, etc.)
5. Provide a solution following the specified format

Remember: Do NOT create a merge request. Only analyze and propose solutions."""
        
        # Create fresh agent for analysis
        agent = Agent(
            model=self.model,
            system_prompt=PIPELINE_SYSTEM_PROMPT,
            tools=self.tools
        )
        
        # Run analysis
        result = await agent.invoke_async(prompt)
        log.info(f"Analysis complete for session {session_id}")
        
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
        log.info(f"Handling user message for session {session_id}")
        
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
            branch_name = f"gitlab_agent_fix_{timestamp}"
            
            final_prompt = f"""{context_text}

The user wants to create a merge request with the fixes.

Project ID: {context['project_id']}
Branch Name: {branch_name}

Based on the previous analysis, create a merge request with the necessary fixes.
Use the create_merge_request tool with the exact file changes discussed."""
        else:
            final_prompt = f"{context_text}\n{message}" if context_text else message
        
        # Create fresh agent and invoke
        agent = Agent(
            model=self.model,
            system_prompt=PIPELINE_SYSTEM_PROMPT,
            tools=self.tools
        )
        
        result = await agent.invoke_async(final_prompt)
        log.debug(f"Generated response for session {session_id}")
        
        # Return the message directly
        return result.message