"""SonarQube quality analysis agent"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from strands import Agent, tool
import os, re
from strands.models.bedrock import BedrockModel
from strands.models.anthropic import AnthropicModel
from utils.logger import log
from config import settings
from db.models import SessionContext
from db.session_manager import SessionManager
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

def get_quality_system_prompt(max_attempts: int = None):
    if max_attempts is None:
        max_attempts = settings.max_fix_attempts
        
    return f"""You are an expert code quality analyst specialized in SonarQube quality gate failures.

## Your Role
Analyze quality issues and provide actionable fixes. When analyzing, always fetch the actual metrics first.

## Important Rules for Comprehensive Analysis
- ALWAYS fetch and analyze the latest pipeline logs when quality gate fails to understand the full context
- Check both SonarQube metrics AND pipeline execution logs for complete diagnosis
- Look for patterns between quality issues and runtime failures
- When iterating on fixes, review what changed in the pipeline logs between attempts

## Analysis Process for Quality Gate Failures
1. Get project metrics from SonarQube
2. Get all issues by type (BUG, VULNERABILITY, CODE_SMELL)
3. Fetch the latest pipeline job logs to understand execution context and check whether it's an actual quality issue or regular pipeline failure
4. Check if there are compilation or runtime issues alongside quality issues
5. Analyze findings holistically - both static analysis and runtime behavior
6. Propose solutions that address both quality and execution issues

## For Iteration Attempts
When analyzing after a failed fix attempt:
1. First check the pipeline logs to see what specifically failed
2. Compare with previous iteration logs to identify what changed
3. Adjust the fix based on both quality metrics AND execution feedback
4. Don't just retry the same fix - evolve based on the failure pattern

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

Analysis approach:
1. Get project metrics
2. Get all project issues - they contain file paths in the 'component' field
3. Extract file paths from the issues and retrieve those specific files
4. File paths in SonarQube format: "project_key:path/to/file.ext"
5. Extract the path after the colon for file retrieval
6. Only create MR if you successfully retrieved files with issues"""
        
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
                
                # Return the content string for successful retrieval
                if result.get("status") == "success":
                    return result.get("content", "")
                else:
                    return f"Error: {result.get('error', 'Failed to get file content')}"
            
            # If result is already a string, return it
            return str(result)
        
        # Create tools list with tracked version
        tools = [
            get_project_quality_gate_status,
            get_project_issues,
            get_project_metrics,
            get_issue_details,
            get_rule_description,
            tracked_get_file_content,
            get_project_info
        ]
        
        # Create fresh agent for analysis
        agent = Agent(
            model=self.model,
            system_prompt=get_quality_system_prompt(),
            tools=tools
        )
        
        result = await agent.invoke_async(prompt)
        log.info(f"Quality analysis complete for session {session_id}")
        
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
            
        # Store analysis data
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
        """Handle user message in conversation"""
        log.info(f"Handling user message for quality session {session_id}")
        
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
        
        # Check iteration limit (continued from previous part)
        if is_retry or is_apply_fix or (is_mr_request and len(fix_attempts) > 0):
            if await self._session_manager.check_iteration_limit(session_id):
                max_attempts = settings.max_fix_attempts
                return f"""### ❌ Iteration Limit Reached

I've attempted to fix quality issues {max_attempts} times but the quality gate continues to fail. This suggests:

1. **Deep architectural issues** requiring refactoring
2. **Complex security vulnerabilities** needing manual review
3. **Test coverage gaps** requiring new test implementation

### 🔍 Recommended Actions:
1. Review all quality issues in SonarQube dashboard
2. Check the merge requests created for partial fixes
3. Prioritize critical security vulnerabilities manually
4. Consider breaking fixes into smaller, focused MRs

### 📋 Fix Attempts Made:
""" + "\n".join([f"- Attempt #{att['attempt_number']}: {att['branch_name']} - {att['status']}" for att in fix_attempts])
        
        # Build context prompt
        context_prompt = f"""
Session Context:
- Project: {context.project_name}
- SonarQube Key: {context.sonarqube_key}
- GitLab Project ID: {context.gitlab_project_id}
- Quality Gate Status: {context.quality_gate_status}
- Session ID: {session_id}
- Current Fix Branch: {current_fix_branch or 'None'}
- Fix Iteration: {len(fix_attempts)} of {settings.max_fix_attempts}
"""
        
        # Add conversation summary (last analysis)
        if conversation_history:
            for msg in reversed(conversation_history):
                if msg["role"] == "assistant" and msg.get("content"):
                    context_prompt += f"\n\nPrevious Analysis:\n{msg['content']}"
                    break
        
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
- Project ID: {context.gitlab_project_id}
- Source Branch: {current_fix_branch}
- Target Branch: {context.branch or 'main'}
- Title: Additional quality fixes (Iteration {len(fix_attempts) + 1})
- Description: Iterative fix for quality gate failures
- update_mode: true

CRITICAL: Set update_mode=true since we're updating an existing branch."""
            else:
                # Create new branch and MR
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                branch_name = f"fix/sonarqube_{timestamp}"
                
                final_prompt = f"""{context_prompt}

The user wants to create a merge request with the quality fixes.

INSTRUCTIONS:
1. Use available tools to get stored analysis and tracked files
2. Review the previous analysis to understand what fixes are needed
3. For each file that needs changes:
   - If it was tracked and retrieved, use the stored content
   - If it's a new file that needs to be created, create it
   - Apply the fixes that were discussed in the analysis
4. Create a merge request with ALL necessary files
5. Include the complete MR URL in your response

Use these parameters for create_merge_request:
- Project ID: {context.gitlab_project_id}
- Source Branch: {branch_name}
- Target Branch: {context.branch or 'main'}
- Title: Fix SonarQube quality gate failures
- Description: Automated fixes for bugs, vulnerabilities, and code smells

The files parameter must be a dictionary with this structure:
{{
    "updates": {{
        "path/to/existing/file.ext": "complete file content here"
    }},
    "creates": {{
        "path/to/new/file.ext": "complete file content here"
    }}
}}"""
        else:
            final_prompt = f"{context_prompt}\n\nUser Question: {message}"
        
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
                
                # Return the content string for successful retrieval
                if result.get("status") == "success":
                    return result.get("content", "")
                else:
                    return f"Error: {result.get('error', 'Failed to get file content')}"
            
            # If result is already a string, return it
            return str(result)
        
        # Create tools list including session-specific tool
        tools = [
            get_project_quality_gate_status,
            get_project_issues,
            get_project_metrics,
            get_issue_details,
            get_rule_description,
            tracked_get_file_content,
            create_merge_request,
            get_project_info,
            get_session_data
        ]
        
        # Create fresh agent and invoke
        agent = Agent(
            model=self.model,
            system_prompt=get_quality_system_prompt(),
            tools=tools
        )
        
        result = await agent.invoke_async(final_prompt)
        
        # Extract text from result
        result_text = self.extract_text_from_response(result)
        
        # Track fix attempt if MR was created
        if is_mr_request and ("web_url" in result_text or "merge_requests" in result_text):
            # Extract MR URL from the response - this is the only regex we need
            mr_url_match = re.search(r'(https?://[^\s<>"]+/merge_requests/\d+)', result_text)
            
            if mr_url_match:
                mr_url = mr_url_match.group(1)
                mr_id = mr_url.split('/')[-1]
                
                # Query GitLab API to get the actual MR details
                from tools.gitlab import get_gitlab_client
                
                try:
                    async with await get_gitlab_client() as client:
                        response = await client.get(f"/projects/{context.gitlab_project_id}/merge_requests/{mr_id}")
                        
                        if response.status_code == 200:
                            mr_data = response.json()
                            branch_name = mr_data.get('source_branch')
                            
                            # Also get the files changed from the MR API
                            changes_response = await client.get(f"/projects/{context.gitlab_project_id}/merge_requests/{mr_id}/changes")
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