"""SonarQube quality analysis agent"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from strands import Agent, tool
import os
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
        
        # Session storage for tracking files
        self.session_files = {}
        self._current_session_id = None
        self._session_manager = SessionManager()
        
        # Create wrapped get_file_content to track accessed files
        original_get_file_content = get_file_content
        
        @tool
        async def tracked_get_file_content(file_path: str, project_id: str, ref: str = "HEAD") -> str:
            """Get content of a file from GitLab repository"""
            result = await original_get_file_content(file_path, project_id, ref)
            
            # Track and store successful file access
            if self._current_session_id and "Error getting file content" not in result:
                if self._current_session_id not in self.session_files:
                    self.session_files[self._current_session_id] = {}
                
                # Store both path and content
                self.session_files[self._current_session_id][file_path] = result
                log.debug(f"Tracked and stored content for: {file_path}")
            
            return result
        
        # Tool to get stored file analysis
        @tool
        async def get_stored_file_analysis() -> Dict[str, Any]:
            """Get stored file analysis for current session"""
            if self._current_session_id:
                session = await self._session_manager.get_session(self._current_session_id)
                if session:
                    return session.get('webhook_data', {}).get('file_analysis', {})
            return {}
        
        # Store tools
        self.tools = [
            get_project_quality_gate_status,
            get_project_issues,
            get_project_metrics,
            get_issue_details,
            get_rule_description,
            tracked_get_file_content,
            create_merge_request,
            get_project_info,
            get_stored_file_analysis
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
        
        # Set current session for file tracking
        self._current_session_id = session_id
        
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
        
        # Store tracked files and analysis
        await self._store_analysis_data(session_id, str(result))
        
        # Clear current session
        self._current_session_id = None
        
        # Extract text from result
        if hasattr(result, 'message'):
            return result.message
        return str(result)
    
    async def _store_analysis_data(self, session_id: str, result_text: str):
        """Store tracked files and analysis data"""
        import re
        
        # Get tracked files and content for this session
        tracked_files_content = self.session_files.get(session_id, {})

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

        # Get current session data
        session = await self._session_manager.get_session(session_id)
        webhook_data = session.get('webhook_data', {})

        # Initialize file_analysis
        if 'file_analysis' not in webhook_data:
            webhook_data['file_analysis'] = {}

        # Store all tracked files with their original content
        for file_path, original_content in tracked_files_content.items():
            webhook_data['file_analysis'][file_path] = {
                'original_content': original_content,
                'proposed_changes': None,  # Will be determined by LLM during MR creation
                'timestamp': datetime.utcnow().isoformat()
            }

        # Store the full analysis result for later use
        webhook_data['analysis_result'] = result_text
        webhook_data['code_blocks'] = code_blocks

        # Update session
        await self._session_manager.update_session_metadata(
            session_id,
            {
                "webhook_data": webhook_data,
                "tracked_files": list(tracked_files_content.keys())
            }
        )

        log.info(f"Stored analysis data with {len(tracked_files_content)} tracked files and {len(code_blocks)} code blocks")
    
    async def handle_user_message(
        self,
        session_id: str,
        message: str,
        conversation_history: List[Dict[str, Any]],
        context: SessionContext
    ) -> str:
        """Handle user message in conversation"""
        log.info(f"Handling user message for quality session {session_id}")
        
        # Set current session for file tracking
        self._current_session_id = session_id
        
        # Check message intent
        is_retry = "still failing" in message.lower() or "same error" in message.lower() or "try again" in message.lower()
        is_mr_request = "create" in message.lower() and ("mr" in message.lower() or "merge request" in message.lower())
        is_apply_fix = "apply" in message.lower() and "fix" in message.lower()
        
        # Check if current branch is a fix branch
        is_fix_branch = context.branch and context.branch.startswith("fix/sonarqube_")
        
        # Get fix attempts
        fix_attempts = await self._session_manager.get_fix_attempts(session_id)
        
        # Check iteration limit
        if is_retry or is_apply_fix or (is_mr_request and len(fix_attempts) > 0):
            if await self._session_manager.check_iteration_limit(session_id):
                self._current_session_id = None
                return """### ❌ Iteration Limit Reached

I've attempted to fix quality issues 5 times but the quality gate continues to fail. This suggests:

1. **Deep architectural issues** requiring refactoring
2. **Complex security vulnerabilities** needing manual review
3. **Test coverage gaps** requiring new test implementation

### 🔍 Recommended Actions:
1. Review all quality issues in SonarQube dashboard
2. Check the merge requests created for partial fixes
3. Prioritize critical security vulnerabilities manually
4. Consider breaking fixes into smaller, focused MRs

### 📋 Fix Attempts Made:
""" + "\n".join([f"- MR #{att['mr_id']} on branch `{att['branch']}`" for att in fix_attempts])
        
        # Build context prompt
        context_prompt = f"""
Session Context:
- Project: {context.project_name}
- SonarQube Key: {context.sonarqube_key}
- GitLab Project ID: {context.gitlab_project_id}
- Quality Gate Status: {context.quality_gate_status}
- Session ID: {session_id}
"""
        
        # Add conversation summary (last analysis)
        if conversation_history:
            for msg in reversed(conversation_history):
                if msg["role"] == "assistant" and "Proposed Fixes" in msg.get("content", ""):
                    context_prompt += f"\n\nPrevious Analysis:\n{msg['content']}"
                    break
        
        # Prepare final prompt based on context
        if is_mr_request and not is_fix_branch:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            branch_name = f"fix/sonarqube_{timestamp}"
            
            final_prompt = f"""{context_prompt}

The user wants to create a merge request with the quality fixes.

INSTRUCTIONS:
1. First, call get_stored_file_analysis() to retrieve the file analysis from the session
2. Review the previous analysis in the conversation to understand what fixes are needed
3. For each file that was tracked:
   - If it needs changes based on the analysis, determine the complete fixed content
   - If it's a new file that needs to be created, create it
4. Create a merge request with ALL necessary files
5. Include the complete MR URL in your response

Use these parameters for create_merge_request:
- Project ID: {context.gitlab_project_id}
- Source Branch: {branch_name}
- Target Branch: {context.branch or 'main'}
- Title: Fix SonarQube quality gate failures
- Description: Automated fixes for bugs, vulnerabilities, and code smells

CRITICAL: The files parameter must be a dictionary with this EXACT structure:
{{
    "updates": {{
        "path/to/existing/file.ext": "complete file content here"
    }},
    "creates": {{
        "path/to/new/file.ext": "complete file content here"
    }}
}}

IMPORTANT RULES:
- Check which files you retrieved successfully with get_file_content
- Files that returned content go in "updates" 
- Files that returned "Error getting file content" or don't exist go in "creates"
- Include the COMPLETE content for each file, not just the changes"""
        elif is_apply_fix or (is_mr_request and is_fix_branch):
            # Applying fix to existing branch
            final_prompt = f"""{context_prompt}

The user wants to apply additional fixes to the existing feature branch: {context.branch}

INSTRUCTIONS:
1. Review the latest failure and previous attempts
2. Identify what additional fixes are needed
3. Apply fixes to the same branch by updating or creating files as needed

Use these parameters for create_merge_request:
- Project ID: {context.gitlab_project_id}
- Source Branch: {context.branch}
- Target Branch: main
- Title: Additional quality fixes
- Description: Iterative fix for quality gate failures
- update_mode: true

CRITICAL: Set update_mode=true since we're updating an existing branch.
The files parameter must use the same structure:
{{
    "updates": {{}},
    "creates": {{}}
}}"""
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
        
        # Clear current session
        self._current_session_id = None
        
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