"""Pipeline failure analysis agent"""
from typing import Dict, Any, List
from datetime import datetime
from strands import Agent, tool
import os, json, asyncio
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

PIPELINE_SYSTEM_PROMPT = """You are an expert DevOps engineer specialized in analyzing GitLab CI/CD pipeline failures.

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
- When you analyze files, ALWAYS retrieve them using get_file_content to see the actual content"""

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
        
        # Create fresh agent for analysis
        agent = Agent(
            model=self.model,
            system_prompt=PIPELINE_SYSTEM_PROMPT,
            tools=self.tools
        )
        
        # Run analysis
        result = await agent.invoke_async(prompt)
        log.info(f"Analysis complete for session {session_id}")
        
        if hasattr(result, 'message'):
            result_text = result.message
        elif hasattr(result, 'content'):
            result_text = result.content
        elif isinstance(result, dict):
            result_text = result.get('content', str(result))
        else:
            result_text = str(result)

        # Ensure it's a string
        if not isinstance(result_text, str):
            result_text = str(result_text)
        
        # Extract and store file changes from the analysis
        await self._extract_and_store_file_changes(session_id, result_text)
        
        # Return the text
        return result_text
    
    async def _extract_and_store_file_changes(self, session_id: str, result_text: str):
        import re
        
        # Extract file paths mentioned in the analysis
        """Extract code changes from analysis result"""
        file_patterns = [
            r'File:\s*`?([^\s`]+)`?',  # File: path/to/file
            r'//\s*([^\s]+\.java)',     # Comments with file paths
            r'src/[^\s]+\.java',        # Java files
            r'src/[^\s]+\.py',          # Python files
            r'[^\s]+\.yml',             # YAML files
            r'[^\s]+\.xml',             # XML files
        ]
        
        files_mentioned = []
        for pattern in file_patterns:
            matches = re.findall(pattern, result_text)
            files_mentioned.extend(matches)
        
        # Remove duplicates while preserving order
        seen = set()
        files_mentioned = [x for x in files_mentioned if not (x in seen or seen.add(x))]
        
        # Extract code blocks with their language
        code_blocks = []
        code_pattern = r'```(?:java|python|javascript|yaml|xml)?\n(.*?)\n```'
        matches = re.findall(code_pattern, result_text, re.DOTALL)
        
        # Map files to code blocks
        file_changes = {}
        
        # Look for file paths in comments within code blocks
        for code in matches:
            # Check for file path comment at the beginning
            file_comment_match = re.match(r'//\s*([^\n]+\.java)', code)
            if file_comment_match:
                file_path = file_comment_match.group(1).strip()
                # Remove the comment line from the code
                code_without_comment = '\n'.join(code.split('\n')[1:])
                file_changes[file_path] = code_without_comment
            else:
                # Try to match based on class names
                for file_path in files_mentioned:
                    file_name = os.path.basename(file_path)
                    class_name = file_name.replace('.java', '').replace('.py', '')
                    
                    if f'class {class_name}' in code or f'public class {class_name}' in code:
                        file_changes[file_path] = code
                        break
        
        # Store the analysis data
        analysis_data = {
            'files': files_mentioned,
            'changes': file_changes,
            'full_message': result_text,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        log.info(f"Storing file changes for session {session_id}:")
        log.info(f"  Files mentioned: {files_mentioned}")
        log.info(f"  File changes mapped: {list(file_changes.keys())}")
        
        # Store in database
        try:
            session_manager = SessionManager()
            await session_manager.store_analyzed_files(session_id, analysis_data)
        except Exception as e:
            log.error(f"Failed to store analyzed files: {e}")
    
    async def handle_user_message(
        self,
        session_id: str,
        message: str,
        conversation_history: List[Dict[str, Any]],
        context: SessionContext
    ) -> str:
        """Handle user message with full context"""
        log.info(f"Handling message for pipeline session {session_id}")
        
        # Check message intent
        is_retry = "still failing" in message.lower() or "same error" in message.lower() or "try again" in message.lower()
        is_mr_request = "create" in message.lower() and ("mr" in message.lower() or "merge request" in message.lower())
        is_apply_fix = "apply" in message.lower() and "fix" in message.lower()
        
        # Check if current branch is a fix branch
        is_fix_branch = context.branch and context.branch.startswith("fix/pipeline_")
        
        # Get fix attempts
        session_manager = SessionManager()
        fix_attempts = await session_manager.get_fix_attempts(session_id)
        
        # Check iteration limit
        if is_retry or is_apply_fix or (is_mr_request and len(fix_attempts) > 0):
            if await session_manager.check_iteration_limit(session_id):
                return """### ❌ Iteration Limit Reached

I've attempted to fix this issue 5 times but the pipeline continues to fail. This suggests:

1. **Multiple interrelated issues** that require comprehensive analysis
2. **Environmental problems** not visible in truncated logs
3. **Complex dependencies** that need manual investigation

### 🔍 Recommended Actions:
1. Review the full pipeline logs in GitLab (not truncated)
2. Check the merge requests created for partial fixes
3. Run the pipeline locally to debug
4. Consider breaking the problem into smaller, testable changes

### 📋 Fix Attempts Made:
""" + "\n".join([f"- MR #{att['mr_id']} on branch `{att['branch']}`" for att in fix_attempts])
        
        # Build context prompt - keep it concise
        context_prompt = f"""
Session Context:
- Project: {context.project_name} (ID: {context.project_id})
- Pipeline: #{context.pipeline_id}
- Branch: {context.branch}
- Failed Job: {context.job_name} in stage {context.failed_stage}
- Is Fix Branch: {is_fix_branch}
- Fix Attempts: {len(fix_attempts)}
"""
        
        # Get existing branch info if available
        existing_fix_branch = None
        existing_mr_id = None
        if fix_attempts:
            latest_attempt = fix_attempts[-1]
            existing_fix_branch = latest_attempt.get('branch')
            existing_mr_id = latest_attempt.get('mr_id')
        
        # Prepare final prompt based on context
        if is_mr_request and not is_fix_branch:
            # First fix - create new branch
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            branch_name = f"fix/pipeline_{context.job_name}_{timestamp}".replace(" ", "_").lower()
            
            # Get analyzed files from database
            analyzed_data = await session_manager.get_analyzed_files(session_id)
            
            # Extract the proposed solution from previous analysis
            full_message = analyzed_data.get('full_message', '')
            
            final_prompt = f"""{context_prompt}

The user wants to create a merge request with the fixes discussed.

Previous Analysis Summary:
{full_message[:1500]}...

CRITICAL INSTRUCTIONS:
1. First, use get_file_content to retrieve the actual content of files that need to be modified
2. Apply the fixes discussed in the analysis
3. Create a merge request with the complete fixed files
4. Include the complete MR URL in your response

For the Library.java issue, you need to:
- Add null checks in borrowBook method
- Add BookNotFoundException handling
- Fix the returnBook and addBook methods

Use these parameters:
- Project ID: {context.project_id}
- Source Branch: {branch_name}
- Target Branch: {context.branch or 'main'}
- Title: Fix {context.failed_stage} failure in {context.job_name}
- Description: Automated fix for pipeline failure #{context.pipeline_id}

Retrieve the files and create the merge request now."""
        else:
            final_prompt = f"""{context_prompt}

Previous Conversation:
{self._format_conversation_history(conversation_history)}

User Question: {message}

Note: When retrieving logs, always use max_size=30000 to prevent overflow."""
        
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