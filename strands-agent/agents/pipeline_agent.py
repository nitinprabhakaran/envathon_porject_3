"""Pipeline failure analysis agent"""
from typing import Dict, Any, List
from datetime import datetime
from strands import Agent
import os
from strands.models.bedrock import BedrockModel
from strands.models.anthropic import AnthropicModel
from utils.logger import log
from config import settings
from db.models import SessionContext
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

## Important: Log Size Management
When retrieving job logs, ALWAYS specify max_size parameter (e.g., 100000 characters) to prevent context overflow.
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
- Branch names should be: fix/pipeline_[job_name]_[timestamp]
- When creating MR, ALWAYS include the full MR URL in your response
- When calling get_job_logs, ALWAYS use max_size parameter (recommended: 100000)"""

class PipelineAgent:
    def __init__(self):
        # Initialize LLM based on provider
        if settings.llm_provider == "bedrock":
            # Get model ID from environment
            model_id = os.getenv("MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
            region = settings.aws_region
            
            log.info(f"Initializing Bedrock model:")
            log.info(f"  Original MODEL_ID: {model_id}")
            log.info(f"  AWS Region: {region}")
            
            # Check if it's a cross-region inference profile
            is_cross_region = False
            if model_id.startswith(("us.", "eu.", "ap.")):
                is_cross_region = True
                log.info(f"  Detected cross-region inference profile prefix")
            elif "arn:aws:bedrock" in model_id:
                is_cross_region = True
                log.info(f"  Detected ARN format for cross-region")
            
            # If not already in cross-region format, convert it
            if not is_cross_region and settings.aws_region != "us-east-1":
                # Convert to cross-region inference profile
                original_model_id = model_id
                model_id = f"us.{model_id}"
                log.info(f"  Converted to cross-region format: {model_id}")
                log.info(f"  (Original: {original_model_id})")
            
            log.info(f"  Final MODEL_ID: {model_id}")
            log.info(f"  Is Cross-Region: {is_cross_region or model_id.startswith(('us.', 'eu.', 'ap.'))}")
            
            try:
                self.model = BedrockModel(
                    model_id=model_id,
                    region=region,
                    temperature=0.1,
                    streaming=False,  # Changed to False - streaming might cause issues
                    max_tokens=4096,
                    top_p=0.8,
                    # Additional parameters that might be needed
                    credentials_profile_name=os.getenv("AWS_PROFILE", None),
                    aws_access_key_id=settings.aws_access_key_id,
                    aws_secret_access_key=settings.aws_secret_access_key,
                    aws_session_token=settings.aws_session_token
                )
                log.info("  ✓ Bedrock model initialized successfully")
            except Exception as e:
                log.error(f"  ✗ Failed to initialize Bedrock model: {e}")
                raise
        else:
            self.model = AnthropicModel(
                model_id=os.getenv("MODEL_ID", "claude-3-haiku-20240307"),
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
        
        # Sort failed jobs by finished_at timestamp to get the most recent failure
        failed_jobs.sort(key=lambda x: x.get("finished_at", ""), reverse=True)
        
        # Check if this is a quality gate failure
        quality_gate_job = None
        for job in failed_jobs:
            if any(keyword in job.get('name', '').lower() for keyword in ['sonar', 'quality', 'scan']):
                quality_gate_job = job
                break
        
        # Create analysis prompt
        failed_job = failed_jobs[0]  # Focus on first failure
        
        if quality_gate_job:
            prompt = f"""Analyze this pipeline failure:

Project ID: {project_id}
Pipeline ID: {pipeline_id}
Failed Job: {quality_gate_job.get('name', 'unknown')}
Stage: {quality_gate_job.get('stage', 'unknown')}

IMPORTANT: This appears to be a SonarQube quality gate failure.

Use the available tools to:
1. Get the job logs (use max_size=100000 to prevent overflow)
2. If confirmed, provide a brief summary and recommend using the Quality Issues tab
3. Do NOT attempt to fix quality issues here - they should be handled in the Quality Issues tab

Follow the analysis format but focus on explaining this is a quality issue."""
        else:
            prompt = f"""Analyze this pipeline failure:

Project ID: {project_id}
Pipeline ID: {pipeline_id}
Failed Job: {failed_job.get('name', 'unknown')}
Stage: {failed_job.get('stage', 'unknown')}
Failure Reason: {failed_job.get('failure_reason', 'unknown')}

Use the available tools to:
1. Get the pipeline jobs and identify all failures
2. Get logs for the failed job(s) - IMPORTANT: use max_size=100000 parameter
3. Analyze the error and determine root cause
4. If needed, examine relevant files (CI config, dependencies, etc.)
5. Provide a solution following the specified format

Note: 
- Always use max_size=100000 when calling get_job_logs to prevent context overflow
- If logs are truncated, focus on the available portions
- If you need to check shared pipeline templates, they are in a separate project

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
        context: SessionContext
    ) -> str:
        """Handle user message with full context"""
        log.info(f"Handling message for pipeline session {session_id}")
        
        # Check for MR creation request
        is_mr_request = "create" in message.lower() and ("mr" in message.lower() or "merge request" in message.lower())
        
        # Build context prompt - keep it concise
        context_prompt = f"""
Session Context:
- Project: {context.project_name} (ID: {context.project_id})
- Pipeline: #{context.pipeline_id}
- Branch: {context.branch}
- Failed Job: {context.job_name} in stage {context.failed_stage}
"""
        
        # Add only the most recent analysis summary
        if conversation_history and len(conversation_history) > 0:
            # Limit conversation history to last 3 exchanges to save tokens
            recent_history = conversation_history[-6:] if len(conversation_history) > 6 else conversation_history
            
            for msg in reversed(recent_history):
                if msg["role"] == "assistant" and "Proposed Solution" in msg.get("content", ""):
                    # Extract just the solution part
                    content = msg['content']
                    if "### 💡 Proposed Solution" in content:
                        solution_part = content.split("### 💡 Proposed Solution")[1]
                        if "### " in solution_part:
                            solution_part = solution_part.split("### ")[0]
                        context_prompt += f"\n\nPrevious Solution Summary:\n{solution_part[:500]}..."
                    break
        
        # Prepare final prompt
        if is_mr_request:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            branch_name = f"fix/pipeline_{context.job_name}_{timestamp}".replace(" ", "_").lower()
            
            final_prompt = f"""{context_prompt}

The user wants to create a merge request with the fixes.

CRITICAL INSTRUCTIONS:
1. Use the create_merge_request tool with the exact file changes from the previous analysis
2. After creating the MR, you MUST include the complete MR URL in your response
3. Format your response to clearly show:
   - What files were changed
   - The branch name created
   - **The full merge request URL** (e.g., https://gitlab.example.com/group/project/-/merge_requests/123)

Use these parameters:
- Project ID: {context.project_id}
- Source Branch: {branch_name}
- Target Branch: {context.branch or 'main'}
- Title: Fix {context.failed_stage} failure in {context.job_name}
- Description: Automated fix for pipeline failure #{context.pipeline_id}

Create the merge request now."""
        else:
            final_prompt = f"{context_prompt}\n\nUser Question: {message}\n\nNote: When retrieving logs, always use max_size=100000 to prevent overflow."
        
        # Create agent with tools
        agent = Agent(
            model=self.model,
            system_prompt=PIPELINE_SYSTEM_PROMPT,
            tools=self.tools
        )
        
        result = await agent.invoke_async(final_prompt)
        log.debug(f"Generated response for session {session_id}")
        
        # Return the message directly
        return result.message if hasattr(result, 'message') else str(result)