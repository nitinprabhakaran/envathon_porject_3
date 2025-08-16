"""Base agent class with common functionality following Strands Agent best practices"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import os
import re
from datetime import datetime

from utils.logger import log
from config import settings
from db.models import SessionContext
from db.session_manager import SessionManager


class BaseAnalysisAgent(ABC):
    """Base class for analysis agents with common Strands Agent patterns"""
    
    def __init__(self, agent_type: str):
        """Initialize base agent with model and session manager"""
        self.agent_type = agent_type
        self.model = self._initialize_model()
        self._session_manager = SessionManager()
        log.info(f"{agent_type} agent initialized")
    
    def _initialize_model(self):
        """Initialize LLM model based on configuration"""
        if settings.llm_provider == "bedrock":
            return self._create_bedrock_model()
        elif settings.llm_provider == "anthropic":
            return self._create_anthropic_model()
        else:
            raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")
    
    def _create_bedrock_model(self):
        """Create and configure Bedrock model with proper cross-region handling"""
        from strands.models.bedrock import BedrockModel
        
        model_id = settings.model_id
        region = settings.aws_region
        
        log.info(f"Initializing Bedrock model:")
        log.info(f"  Original MODEL_ID: {model_id}")
        log.info(f"  AWS Region: {region}")
        
        # Handle cross-region model IDs
        is_cross_region = (
            model_id.startswith(("us.", "eu.", "ap.")) or 
            "arn:aws:bedrock" in model_id
        )
        
        if not is_cross_region and region != "us-east-1":
            original_model_id = model_id
            model_id = f"us.{model_id}"
            log.info(f"  Converted to cross-region format: {model_id}")
            log.info(f"  (Original: {original_model_id})")
        
        log.info(f"  Final MODEL_ID: {model_id}")
        
        try:
            model = BedrockModel(
                model_id=model_id,
                region=region,
                temperature=0.1,
                streaming=False,
                max_tokens=4096,
                top_p=0.8,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                aws_session_token=settings.aws_session_token
            )
            log.info("  ✓ Bedrock model initialized successfully")
            return model
        except Exception as e:
            log.error(f"  ✗ Failed to initialize Bedrock model: {e}")
            raise
    
    def _create_anthropic_model(self):
        """Create and configure Anthropic model"""
        from strands.models.anthropic import AnthropicModel
        return AnthropicModel(
            model_id=settings.model_id,
            api_key=settings.anthropic_api_key,
            temperature=0.3,
            max_tokens=4096
        )
    
    def create_tracked_file_tool(self, session_id: str, current_fix_branch: Optional[str] = None):
        """Create a tracked file content tool for the session"""
        from tools.gitlab import get_file_content
        from strands import tool
        
        @tool
        async def get_file_content_tracked(
            file_path: str, 
            project_id: str, 
            ref: str = "HEAD"
        ) -> str:
            """Get content of a file from GitLab repository and automatically track it in the current session"""
            # Use current fix branch if available
            if current_fix_branch and ref == "HEAD":
                ref = current_fix_branch
                
            result = await get_file_content(file_path, project_id, ref)
            
            # Store file immediately in database
            if isinstance(result, dict):
                await self._session_manager.store_tracked_file(
                    session_id,
                    file_path,
                    result.get("content") if result.get("status") == "success" else None,
                    result.get("status", "error")
                )
                
                # Return appropriate response
                if result.get("status") == "success":
                    return result.get("content", "")
                else:
                    return f"Error: {result.get('error', 'Failed to get file content')}"
            
            return str(result)
        
        return get_file_content_tracked
    
    def create_session_data_tool(self, session_id: str):
        """Create a tool to retrieve session data"""
        from strands import tool
        
        @tool
        async def get_session_data() -> Dict[str, Any]:
            """Get stored analysis data and tracked files from the current session for context"""
            session_data = await self._session_manager.get_session(session_id)
            tracked_files = await self._session_manager.get_tracked_files(session_id)
            
            return {
                'analysis_result': session_data.get('webhook_data', {}).get('analysis_result', ''),
                'code_blocks': session_data.get('webhook_data', {}).get('code_blocks', []),
                'tracked_files': tracked_files,
                'current_fix_branch': session_data.get('current_fix_branch'),
                'fix_iteration': session_data.get('fix_iteration', 0)
            }
        
        return get_session_data
    
    async def store_analysis_data(self, session_id: str, result_text: str):
        """Store analysis data with extracted code blocks"""
        if not isinstance(result_text, str):
            result_text = str(result_text)

        # Extract code blocks using regex patterns
        code_blocks = []
        
        # Triple backtick code blocks
        triple_pattern = r'```(?:\w+)?\n(.*?)\n```'
        triple_matches = re.findall(triple_pattern, result_text, re.DOTALL)
        
        # Single backtick code blocks (multiline)
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
    
    def get_agent_tools(self, session_id: str, current_fix_branch: Optional[str] = None, webhook_data: Dict[str, Any] = None) -> List:
        """Get all tools for this agent type dynamically"""
        # Create session-specific tools
        session_tools = [
            self.create_tracked_file_tool(session_id, current_fix_branch),
            self.create_session_data_tool(session_id)
        ]
        
        # Create context tool if webhook data is available
        if webhook_data:
            from utils.context_extractor import ContextExtractor
            context_tool = ContextExtractor.create_context_tool(session_id, webhook_data, self.agent_type.lower())
            session_tools.append(context_tool)
        
        # Get tools from registry based on agent type
        from .tool_registry import tool_registry
        all_tools = tool_registry.get_tools_for_agent(self.agent_type, session_tools)
        
        return all_tools
    
    def get_capabilities_description(self) -> str:
        """Get dynamic capabilities description for this agent type"""
        from .tool_registry import tool_registry
        return tool_registry.get_capability_description(self.agent_type)
    
    async def get_pipeline_logs(self, project_id: str, pipeline_id: str) -> str:
        """Get pipeline logs for analysis"""
        try:
            from tools.gitlab import get_pipeline_jobs, get_job_logs
            
            # Get all jobs in the pipeline
            jobs = await get_pipeline_jobs(pipeline_id, project_id)
            
            # Get logs from failed jobs
            all_logs = []
            for job in jobs:
                if job.get('status') == 'failed':
                    job_logs = await get_job_logs(job['id'], project_id)
                    all_logs.append(f"=== Job: {job.get('name', 'Unknown')} ===\n{job_logs}")
            
            return "\n\n".join(all_logs) if all_logs else "No failed job logs found"
            
        except Exception as e:
            log.error(f"Failed to get pipeline logs: {e}")
            return f"Error retrieving pipeline logs: {str(e)}"
    
    def extract_text_from_response(self, response) -> str:
        """Extract text from Strands Agent response in any format"""
        if isinstance(response, str):
            return response
        
        if hasattr(response, 'message'):
            return str(response.message)
        
        if hasattr(response, 'content'):
            return str(response.content)
        
        if isinstance(response, dict):
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
            elif "message" in response:
                return str(response["message"])
        
        return str(response)
    
    def format_conversation_history(
        self, 
        conversation_history: List[Dict[str, Any]], 
        max_messages: int = 6
    ) -> str:
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
    
    async def check_iteration_limit(self, session_id: str) -> Optional[str]:
        """Check if iteration limit is reached and return appropriate message"""
        # Ensure session_id is string
        session_id = str(session_id)
        
        if await self._session_manager.check_iteration_limit(session_id):
            fix_attempts = await self._session_manager.get_fix_attempts(session_id)
            max_attempts = settings.max_fix_attempts
            
            return f"""### ❌ Iteration Limit Reached

I've attempted to fix this issue {max_attempts} times but it continues to fail. This suggests:

1. **Complex interrelated issues** requiring comprehensive analysis
2. **Environmental problems** not visible in available data
3. **Dependencies** that need manual investigation

### 🔍 Recommended Actions:
1. Review the full logs and analysis in the respective systems
2. Check the merge requests created for partial fixes
3. Consider breaking the problem into smaller, testable changes
4. Manual investigation and testing may be required

### 📋 Fix Attempts Made:
""" + "\n".join([f"- Attempt #{att['attempt_number']}: {att['branch_name']} - {att['status']}" for att in fix_attempts])
        
        return None
    
    async def track_merge_request(
        self, 
        session_id: str, 
        result_text: str, 
        project_id: str,
        is_mr_request: bool
    ) -> str:
        """Track merge request creation and update session data"""
        if not (is_mr_request and ("web_url" in result_text or "merge_requests" in result_text)):
            return result_text
        
        # Extract MR URL from response
        mr_url_match = re.search(r'(https?://[^\s<>"]+/merge_requests/\d+)', result_text)
        
        if not mr_url_match:
            return result_text
        
        mr_url = mr_url_match.group(1)
        mr_id = mr_url.split('/')[-1]
        
        # Query GitLab API for MR details
        from tools.gitlab import get_gitlab_client
        
        try:
            async with await get_gitlab_client() as client:
                response = await client.get(f"/projects/{project_id}/merge_requests/{mr_id}")
                
                if response.status_code == 200:
                    mr_data = response.json()
                    branch_name = mr_data.get('source_branch')
                    
                    # Get files changed
                    changes_response = await client.get(f"/projects/{project_id}/merge_requests/{mr_id}/changes")
                    files_changed = []
                    
                    if changes_response.status_code == 200:
                        changes_data = changes_response.json()
                        for change in changes_data.get('changes', []):
                            files_changed.append(change.get('new_path', change.get('old_path', '')))
                    
                    log.info(f"Retrieved MR details - ID: {mr_id}, Branch: {branch_name}, Files: {files_changed}")
                    
                    if branch_name:
                        await self._update_session_with_mr(
                            session_id, branch_name, mr_id, mr_url, files_changed
                        )
                        
        except Exception as e:
            log.error(f"Error querying GitLab API for MR details: {e}", exc_info=True)
        
        return result_text
    
    async def _update_session_with_mr(
        self, 
        session_id: str, 
        branch_name: str, 
        mr_id: str, 
        mr_url: str, 
        files_changed: List[str]
    ):
        """Update session with merge request information"""
        try:
            # Create fix attempt
            attempt_num = await self._session_manager.create_fix_attempt(
                session_id, branch_name, files_changed
            )
            log.info(f"Created fix attempt #{attempt_num}")
            
            # Update session metadata
            await self._session_manager.update_session_metadata(
                session_id,
                {
                    "merge_request_url": mr_url,
                    "merge_request_id": mr_id,
                    "current_fix_branch": branch_name
                }
            )
            
            # Update fix attempt status
            await self._session_manager.update_fix_attempt(
                session_id, attempt_num, "pending", mr_id, mr_url
            )
            
            # Update webhook data for UI
            await self._update_webhook_data_with_fix(session_id, branch_name, mr_id, mr_url)
            
        except Exception as e:
            log.error(f"Failed to update session with MR: {e}", exc_info=True)
    
    async def _update_webhook_data_with_fix(
        self, 
        session_id: str, 
        branch_name: str, 
        mr_id: str, 
        mr_url: str
    ):
        """Update webhook data with fix attempt information"""
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
            await self._session_manager.update_session_metadata(
                session_id, {"webhook_data": webhook_data}
            )
            log.info("Updated webhook_data with fix attempt")
    
    @abstractmethod
    async def analyze_failure(self, *args, **kwargs) -> str:
        """Abstract method for failure analysis - must be implemented by subclasses"""
        pass
    
    @abstractmethod
    async def handle_user_message(self, *args, **kwargs) -> str:
        """Abstract method for handling user messages - must be implemented by subclasses"""
        pass
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Abstract method for getting system prompt - must be implemented by subclasses"""
        pass
