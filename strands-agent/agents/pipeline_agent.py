"""Pipeline failure analysis agent"""
from typing import Dict, Any, List
from datetime import datetime
from strands import Agent, tool
import os, json, asyncio, re
from strands.models.bedrock import BedrockModel
from strands.models.anthropic import AnthropicModel
from utils.logger import log
from config import settings
from db.models import SessionContext
from db.session_manager import SessionManager
from tools.gitlab import (
    get_pipeline_jobs,
    get_job_logs,
    get_file_content,
    get_recent_commits,
    create_merge_request,
    get_project_info
)

def get_pipeline_system_prompt(max_attempts: int = None):
    """Generate system prompt with configurable max attempts"""
    if max_attempts is None:
        max_attempts = settings.max_fix_attempts
    
    return f"""You are an expert DevOps engineer specialized in analyzing GitLab CI/CD pipeline failures.

## Your Role
Analyze pipeline failures and provide actionable solutions. Every analysis must include:
1. A summary of the probable cause
2. Specific actions to fix the issue
3. Confidence score for your analysis

## Important: Log Size Management
When retrieving job logs, ALWAYS specify max_size parameter (e.g., 30000 characters) to prevent context overflow.
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
- When calling get_job_logs, ALWAYS use max_size parameter (recommended: 30000)
- When you analyze files, ALWAYS retrieve them using get_file_content to see the actual content
- Maximum fix attempts allowed: {max_attempts}

## CRITICAL: Merge Request Response Format
When creating a merge request and reporting back, you MUST include these exact fields in your response:
- Branch: fix/pipeline_[job_name]_[timestamp]
- MR URL: [full URL]

Do NOT use markdown formatting like bullet points or dashes for the branch name. 
Write it as plain text: "Branch: fix/pipeline_build_20250804_163803"
NOT as: "- Branch: fix/pipeline_build_20250804_163803"
"""

class PipelineAgent:
    def __init__(self):
        # Initialize LLM based on provider
        if settings.llm_provider == "bedrock":
            model_id = os.getenv("MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
            region = settings.aws_region
            
            log.info(f"Initializing Bedrock model:")
            log.info(f"  Original MODEL_ID: {model_id}")
            log.info(f"  AWS Region: {region}")
            
            is_cross_region = False
            if model_id.startswith(("us.", "eu.", "ap.")):
                is_cross_region = True
                log.info(f"  Detected cross-region inference profile prefix")
            elif "arn:aws:bedrock" in model_id:
                is_cross_region = True
                log.info(f"  Detected ARN format for cross-region")
            
            if not is_cross_region and settings.aws_region != "us-east-1":
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
                    streaming=False,
                    max_tokens=4096,
                    top_p=0.8,
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
        
        self._session_manager = SessionManager()
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
1. Get the job logs (use max_size=30000 to prevent overflow)
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
2. Get logs for the failed job(s) - IMPORTANT: use max_size=30000 parameter
3. Analyze the error and determine root cause
4. If needed, examine relevant files (CI config, dependencies, etc.) - USE get_file_content to retrieve them
5. Provide a solution following the specified format

CRITICAL: 
- When you identify files that need changes, RETRIEVE them using get_file_content
- Show the COMPLETE fixed content for each file
- Remember the exact file paths and changes for when the user requests an MR

Note: 
- Always use max_size=30000 when calling get_job_logs to prevent context overflow
- If logs are truncated, focus on the available portions
- If you need to check shared pipeline templates, they are in a separate project

Remember: Do NOT create a merge request. Only analyze and propose solutions."""
        
        # Create wrapped get_file_content that stores files immediately
        original_get_file_content = get_file_content
        
        @tool
        async def tracked_get_file_content(file_path: str, project_id: str, ref: str = "HEAD") -> str:
            """Get content of a file from GitLab repository"""
            result = await original_get_file_content(file_path, project_id, ref)
            
            # Store file immediately in database
            if isinstance(result, dict):
                await self._session_manager.store_tracked_file(
                    session_id,
                    file_path,
                    result.get("content") if result.get("status") == "success" else None,
                    result.get("status", "error")
                )
                
                # Return appropriate string based on status
                if result.get("status") == "success":
                    return result.get("content", "")
                else:
                    return f"Error: {result.get('error', 'Failed to get file content')}"
            
            # If result is already a string, return it
            return str(result)
        
        # Create tools list with tracked version
        tools = [
            get_pipeline_jobs,
            get_job_logs,
            tracked_get_file_content,
            get_recent_commits,
            get_project_info
        ]
        
        # Create fresh agent for analysis
        agent = Agent(
            model=self.model,
            system_prompt=get_pipeline_system_prompt(),
            tools=tools
        )
        
        # Run analysis
        result = await agent.invoke_async(prompt)
        log.info(f"Analysis complete for session {session_id}")
        
        # Extract text from result
        if hasattr(result, 'message'):
            result_text = result.message
        elif hasattr(result, 'content'):
            result_text = result.content
        elif isinstance(result, dict):
            # Handle dict response
            if "content" in result:
                content = result["content"]
                if isinstance(content, list) and len(content) > 0:
                    result_text = content[0].get("text", str(result))
                else:
                    result_text = str(content)
            else:
                result_text = result.get("message", str(result))
        else:
            result_text = str(result)
        
        # Store analysis result
        await self._store_analysis_data(session_id, result_text)
        
        return result_text
    
    async def _store_analysis_data(self, session_id: str, result_text: str):
        """Store analysis data"""
        # Ensure result_text is a string
        if not isinstance(result_text, str):
            result_text = str(result_text)

        # Extract all code blocks from the analysis
        code_blocks = []

        # Pattern for triple backtick code blocks
        triple_pattern = r'```(?:\w+)?\n(.*?)\n```'
        triple_matches = re.findall(triple_pattern, result_text, re.DOTALL)

        # Pattern for single backtick code blocks
        single_pattern = r'`(?:\w+)?\n(.*?)\n`'
        single_matches = re.findall(single_pattern, result_text, re.DOTALL)

        code_blocks.extend(triple_matches)
        code_blocks.extend(single_matches)

        # Store the analysis result and code blocks
        await self._session_manager.update_session_metadata(
            session_id,
            {
                "webhook_data": {
                    "analysis_result": result_text,
                    "code_blocks": code_blocks
                }
            }
        )

        log.info(f"Stored analysis data with {len(code_blocks)} code blocks")

    async def handle_user_message(
        self,
        session_id: str,
        message: str,
        conversation_history: List[Dict[str, Any]],
        context: SessionContext
    ) -> str:
        """Handle user message with full context"""
        log.info(f"Handling message for pipeline session {session_id}")
        
        # Create a tool to get stored analysis and files for THIS session
        @tool
        async def get_session_data() -> Dict[str, Any]:
            """Get stored analysis and tracked files from the current session"""
            session_data = await self._session_manager.get_session(session_id)
            tracked_files = await self._session_manager.get_tracked_files(session_id)
            
            return {
                'analysis_result': session_data.get('webhook_data', {}).get('analysis_result', ''),
                'code_blocks': session_data.get('webhook_data', {}).get('code_blocks', []),
                'tracked_files': tracked_files,
                'current_fix_branch': session_data.get('current_fix_branch'),
                'fix_iteration': session_data.get('fix_iteration', 0)
            }
        
        # Check message intent
        is_retry = "still failing" in message.lower() or "same error" in message.lower() or "try again" in message.lower()
        is_mr_request = "create" in message.lower() and ("mr" in message.lower() or "merge request" in message.lower())
        is_apply_fix = "apply" in message.lower() and "fix" in message.lower()
        
        # Get session data to check current state
        session_data = await self._session_manager.get_session(session_id)
        current_fix_branch = session_data.get('current_fix_branch')
        fix_attempts = await self._session_manager.get_fix_attempts(session_id)
        
        # Check iteration limit
        if is_retry or is_apply_fix or (is_mr_request and len(fix_attempts) > 0):
            if await self._session_manager.check_iteration_limit(session_id):
                max_attempts = settings.max_fix_attempts
                return f"""### ❌ Iteration Limit Reached

I've attempted to fix this issue {max_attempts} times but the pipeline continues to fail. This suggests:

1. **Multiple interrelated issues** that require comprehensive analysis
2. **Environmental problems** not visible in truncated logs
3. **Complex dependencies** that need manual investigation

### 🔍 Recommended Actions:
1. Review the full pipeline logs in GitLab (not truncated)
2. Check the merge requests created for partial fixes
3. Run the pipeline locally to debug
4. Consider breaking the problem into smaller, testable changes

### 📋 Fix Attempts Made:
""" + "\n".join([f"- Attempt #{att['attempt_number']}: {att['branch_name']} - {att['status']}" for att in fix_attempts])
        
        # Build context prompt
        context_prompt = f"""
Session Context:
- Project: {context.project_name} (ID: {context.project_id})
- Pipeline: #{context.pipeline_id}
- Branch: {context.branch}
- Failed Job: {context.job_name} in stage {context.failed_stage}
- Session ID: {session_id}
- Current Fix Branch: {current_fix_branch or 'None'}
- Fix Iteration: {len(fix_attempts)} of {settings.max_fix_attempts}
"""
        
        # Prepare final prompt based on context
        if is_mr_request or (is_apply_fix and current_fix_branch):
            if current_fix_branch:
                final_prompt = f"""{context_prompt}

The user wants to apply additional fixes to the existing branch.

INSTRUCTIONS:
1. Use available tools to get stored analysis and tracked files
2. Review what changes were already made on branch: {current_fix_branch}
3. Apply additional fixes to the same branch
4. Update the existing merge request

Use these parameters for create_merge_request:
- Project ID: {context.project_id}
- Source Branch: {current_fix_branch}
- Target Branch: {context.branch or 'main'}
- Title: Additional fixes for {context.failed_stage} failure (Iteration {len(fix_attempts) + 1})
- Description: Iterative fix for pipeline failure #{context.pipeline_id}
- update_mode: true

CRITICAL: Set update_mode=true since we're updating an existing branch."""
            else:
                # Create new branch and MR
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                branch_name = f"fix/pipeline_{context.job_name}_{timestamp}".replace(" ", "_").lower()
                
                final_prompt = f"""{context_prompt}

The user wants to create a merge request with the fixes discussed.

INSTRUCTIONS:
1. Use available tools to get stored analysis and tracked files
2. Review the previous analysis to understand what fixes are needed
3. For each file that needs changes:
   - If it was tracked and retrieved, use the stored content
   - If it's a new file that needs to be created, create it
   - Apply the fixes that were discussed in the analysis
4. Create a merge request with ALL necessary files
5. IMPORTANT: After creating the MR, use get_merge_request_details to retrieve the exact branch name and MR details
6. Include the complete MR URL in your response

Use these parameters for create_merge_request:
- Project ID: {context.project_id}
- Source Branch: {branch_name}
- Target Branch: {context.branch or 'main'}
- Title: Fix {context.failed_stage} failure in {context.job_name}
- Description: Automated fix for pipeline failure #{context.pipeline_id}

The files parameter must be a dictionary with this structure:
{{
    "updates": {{
        "path/to/existing/file.ext": "complete file content here"
    }},
    "creates": {{
        "path/to/new/file.ext": "complete file content here"
    }}
}}

After creating the MR, call get_merge_request_details with the project_id and MR IID to get the exact details."""
        else:
            final_prompt = f"""{context_prompt}

Previous Conversation:
{self._format_conversation_history(conversation_history)}

User Question: {message}

Note: When retrieving logs, always use max_size=30000 to prevent overflow."""
        
        # Create wrapped get_file_content for this session
        original_get_file_content = get_file_content
        
        @tool
        async def tracked_get_file_content(file_path: str, project_id: str, ref: str = "HEAD") -> str:
            """Get content of a file from GitLab repository"""
            # Use current fix branch if available
            if current_fix_branch and ref == "HEAD":
                ref = current_fix_branch
                
            result = await original_get_file_content(file_path, project_id, ref)
            
            # Store file immediately in database
            if isinstance(result, dict):
                await self._session_manager.store_tracked_file(
                    session_id,
                    file_path,
                    result.get("content") if result.get("status") == "success" else None,
                    result.get("status", "error")
                )
            
            return result
        
        # Add tools including session-specific tool
        tools = [
            get_pipeline_jobs,
            get_job_logs,
            tracked_get_file_content,
            get_recent_commits,
            create_merge_request,
            get_project_info,
            get_session_data
        ]
        
        # Create agent with tools
        agent = Agent(
            model=self.model,
            system_prompt=get_pipeline_system_prompt(),
            tools=tools
        )
        
        result = await agent.invoke_async(final_prompt)
        
        # Extract text from result
        result_text = self.extract_text_from_response(result)

        # Track fix attempt if MR was created
        if is_mr_request and ("web_url" in result_text or "merge_requests" in result_text):
            # Extract MR details from the response
            mr_url_match = re.search(r'(https?://[^\s<>"]+/merge_requests/\d+)', result_text)
    
            if mr_url_match:
                mr_url = mr_url_match.group(1)
                mr_id = mr_url.split('/')[-1]

                # Query GitLab API to get the actual MR details
                from tools.gitlab import get_gitlab_client

                try:
                    async with await get_gitlab_client() as client:
                        response = await client.get(f"/projects/{context.project_id}/merge_requests/{mr_id}")

                        if response.status_code == 200:
                            mr_data = response.json()
                            branch_name = mr_data.get('source_branch')

                            # Also get the files changed from the MR API
                            changes_response = await client.get(f"/projects/{context.project_id}/merge_requests/{mr_id}/changes")
                            files_changed = []

                            if changes_response.status_code == 200:
                                changes_data = changes_response.json()
                                for change in changes_data.get('changes', []):
                                    files_changed.append(change.get('new_path', change.get('old_path', '')))

                            log.info(f"Retrieved from GitLab API - MR ID: {mr_id}, Branch: {branch_name}, Files: {files_changed}")

                            if branch_name:
                                # Create fix attempt
                                try:
                                    attempt_num = await self._session_manager.create_fix_attempt(
                                        session_id,
                                        branch_name,
                                        files_changed
                                    )
                                    log.info(f"Created fix attempt #{attempt_num}")

                                    # Update session
                                    await self._session_manager.update_session_metadata(
                                        session_id,
                                        {
                                            "merge_request_url": mr_url,
                                            "merge_request_id": mr_id,
                                            "current_fix_branch": branch_name
                                        }
                                    )

                                    # Update fix attempt
                                    await self._session_manager.update_fix_attempt(
                                        session_id,
                                        attempt_num,
                                        "pending",
                                        mr_id,
                                        mr_url
                                    )

                                    # Update webhook_data for UI
                                    current_session = await self._session_manager.get_session(session_id)
                                    if current_session:
                                        webhook_data = current_session.get("webhook_data", {})
                                        fix_attempts_list = webhook_data.get("fix_attempts", [])
                                        fix_attempts_list.append({
                                            "branch": branch_name,
                                            "mr_id": mr_id,
                                            "mr_url": mr_url,
                                            "status": "pending",
                                            "timestamp": datetime.utcnow().isoformat()
                                        })
                                        webhook_data["fix_attempts"] = fix_attempts_list
                                        await self._session_manager.update_session_metadata(session_id, {"webhook_data": webhook_data})
                                        log.info("Updated webhook_data with fix attempt")

                                except Exception as e:
                                    log.error(f"Failed to create fix attempt: {e}", exc_info=True)
                        else:
                            log.error(f"Failed to get MR details: {response.status_code}")

                except Exception as e:
                    log.error(f"Error querying GitLab API for MR details: {e}", exc_info=True)
        
        log.debug(f"Generated response for session {session_id}")

        # Extract text from result
        if hasattr(result, 'message'):
            result_text = result.message
        elif hasattr(result, 'content'):
            result_text = result.content
        elif isinstance(result, dict):
            # Handle dict response
            if "content" in result:
                content = result["content"]
                if isinstance(content, list) and len(content) > 0:
                    result_text = content[0].get("text", str(result))
                else:
                    result_text = str(content)
            else:
                result_text = result.get("message", str(result))
        else:
            result_text = str(result)
        
        return result_text
    
    def extract_text_from_response(self, response):
        """Extract text from any response format"""
        if isinstance(response, str):
            return response
        
        if hasattr(response, 'message'):
            return str(response.message)
        
        if hasattr(response, 'content'):
            return str(response.content)
        
        if isinstance(response, dict):
            # Handle dict response
            if "content" in response:
                content = response["content"]
                if isinstance(content, list):
                    texts = []
                    for item in content:
                        if isinstance(item, dict) and "text" in item:
                            texts.append(str(item["text"]))
                    return "".join(texts)
                elif isinstance(content, str):
                    return content
                else:
                    return str(content)
            # Try message field
            elif "message" in response:
                return str(response["message"])
        
        return str(response)
    
    def _format_conversation_history(self, conversation_history: List[Dict[str, Any]], max_messages: int = 6) -> str:
        """Format conversation history for context, limiting to recent messages"""
        if not conversation_history:
            return "No previous conversation."
        
        # Take only the last N messages to avoid token overflow
        recent_history = conversation_history[-max_messages:]
        
        formatted = []
        for msg in recent_history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            if role == "system":
                continue  # Skip system messages
            
            # Truncate very long messages
            if len(content) > 1000:
                content = content[:900] + "... [truncated]"
            
            formatted.append(f"{role.upper()}: {content}")
        
        return "\n\n".join(formatted)