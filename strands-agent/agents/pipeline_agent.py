"""Pipeline failure analysis agent"""

from strands import Agent, tool
from typing import Dict, Any, List
import re
from utils.logger import log
from .base_agent import BaseAnalysisAgent
from .prompts import get_pipeline_system_prompt, get_webhook_analysis_prompt
from tools.tool_registry import tool_registry
from utils.context_extractor import ContextExtractor


class PipelineAgent(BaseAnalysisAgent):
    def __init__(self):
        super().__init__("Pipeline")
    
    def get_system_prompt(self) -> str:
        """Return the system prompt for pipeline analysis with dynamic capabilities"""
        capabilities = self.get_capabilities_description()
        return get_pipeline_system_prompt(capabilities)
    
    async def analyze_failure(self, *args, **kwargs) -> str:
        """Analyze pipeline failure and return findings"""
        try:
            # Handle different calling patterns
            if len(args) == 4:
                session_id, project_id, pipeline_id, webhook_data = args
            elif len(args) == 2:
                webhook_data, session_id = args
                project_id = str(webhook_data.get("project", {}).get("id"))
                pipeline_id = str(webhook_data.get("object_attributes", {}).get("id"))
            elif "webhook_data" in kwargs:
                session_id = kwargs.get("session_id") or (args[0] if args else None)
                webhook_data = kwargs["webhook_data"]
                project_id = kwargs.get("project_id") or str(webhook_data.get("project", {}).get("id"))
                pipeline_id = str(webhook_data.get("object_attributes", {}).get("id"))
            else:
                raise ValueError(f"Invalid arguments: args={args}, kwargs={kwargs}")
            
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
            
            # Create analysis prompt using centralized prompt system
            prompt = get_webhook_analysis_prompt(webhook_data, "pipeline", project_id)
            
            # Create wrapped get_file_content that stores files immediately
            # Get the original get_file_content from tools registry
            gitlab_tools = tool_registry.get_tools_for_category("gitlab")
            original_get_file_content = None
            for tool_obj in gitlab_tools:
                if hasattr(tool_obj, '__name__') and tool_obj.__name__ == 'get_file_content':
                    original_get_file_content = tool_obj
                    break
            
            if not original_get_file_content:
                # Fallback: import directly if not found in registry
                from tools.gitlab import get_file_content as original_get_file_content
            
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
            
            # Get tools from registry for pipeline analysis
            gitlab_tools = tool_registry.get_tools_for_category("gitlab")
            
            # Replace create_merge_request with session-aware version
            session_aware_tools = []
            for tool_obj in gitlab_tools:
                if hasattr(tool_obj, '__name__') and tool_obj.__name__ == 'create_merge_request':
                    # Skip the raw create_merge_request - we'll add our session-aware version
                    continue
                session_aware_tools.append(tool_obj)
            
            # Add session-aware create_merge_request
            session_aware_create_mr = self.create_session_aware_create_mr_tool(session_id, project_id)
            session_aware_tools.append(session_aware_create_mr)
            
            # Create tools list with tracked version
            tools = session_aware_tools + [tracked_get_file_content]
            
            # Create fresh agent for analysis
            agent = Agent(
                model=self.model,
                system_prompt=get_pipeline_system_prompt(),
                tools=tools
            )
            
            # Run analysis
            result = await agent.invoke_async(prompt)
            log.info(f"Pipeline analysis complete for session {session_id}")
            
            # Extract text from result
            result_text = self.extract_text_from_response(result)
            
            # Store analysis result
            await self._store_analysis_data(session_id, result_text)
            
            return result_text
            
        except Exception as e:
            log.error(f"Error in pipeline analysis: {e}", exc_info=True)
            return f"Pipeline analysis failed: {str(e)}"
    
    async def handle_user_message(
        self, 
        session_id: str, 
        message: str, 
        conversation_history: List[Dict[str, Any]],
        context: Any
    ) -> str:
        """Handle user message in pipeline analysis context"""
        try:
            log.info(f"Processing user message for pipeline session {session_id}")
            
            # Extract project_id from context
            project_id = str(context.project_id) if hasattr(context, 'project_id') else str(context.get('project_id', 'unknown'))
            
            # Check iteration limit
            limit_message = await self.check_iteration_limit(session_id)
            if limit_message:
                return limit_message
            
            # Get session data
            session_data = await self._session_manager.get_session(session_id)
            current_fix_branch = session_data.get('current_fix_branch') if session_data else None
            webhook_data = session_data.get('webhook_data', {}) if session_data else {}
            
            # Create session-specific tools
            tracked_get_file_content = self.create_tracked_file_tool(session_id, current_fix_branch)
            session_data_tool = self.create_session_data_tool(session_id)
            session_aware_create_mr = self.create_session_aware_create_mr_tool(session_id, project_id)
            
            # Get context tool if webhook data available
            context_tool = None
            if webhook_data:
                from utils.context_extractor import ContextExtractor
                context_tool = ContextExtractor.create_context_tool(session_id, webhook_data, "pipeline")
            
            # Get tools from registry
            gitlab_tools = tool_registry.get_tools_for_category("gitlab")
            
            # Filter out generic create_merge_request to force use of session-aware version
            filtered_gitlab_tools = []
            for tool in gitlab_tools:
                tool_name = None
                if hasattr(tool, 'name'):
                    tool_name = tool.name
                elif hasattr(tool, '__name__'):
                    tool_name = tool.__name__
                
                # Skip the generic create_merge_request tool
                if tool_name != "create_merge_request":
                    filtered_gitlab_tools.append(tool)
            
            gitlab_tools = filtered_gitlab_tools
            
            # Debug tool discovery
            log.info(f"Retrieved {len(gitlab_tools)} gitlab tools from registry (after filtering out generic create_merge_request)")
            if not gitlab_tools:
                log.warning("No gitlab tools found in registry, forcing refresh")
                # Force refresh and try again
                tool_registry.refresh_all_providers()
                gitlab_tools = tool_registry.get_tools_for_category("gitlab")
                log.info(f"After refresh: {len(gitlab_tools)} gitlab tools available")
            
            # Create tools list with session-specific tools and registry tools
            tools = gitlab_tools + [
                tracked_get_file_content,
                session_aware_create_mr,
                session_data_tool
            ]
            
            if context_tool:
                tools.append(context_tool)
            
            # Create agent
            agent = Agent(
                model=self.model,
                system_prompt=self.get_system_prompt(),
                tools=tools
            )
            
            # Format conversation context
            context = self.format_conversation_history(conversation_history)
            from .prompts import get_conversation_continuation_prompt
            continuation_prompt = get_conversation_continuation_prompt("pipeline", context)
            
            # Combine prompts
            full_prompt = f"{continuation_prompt}\n\n## User Request\n{message}"
            
            # Run conversation
            response = await agent.invoke_async(full_prompt)
            result_text = self.extract_text_from_response(response)
            
            # Track merge request if created
            result_text = await self.track_merge_request(
                session_id, result_text, project_id, "merge_request" in message.lower()
            )
            
            log.info("User message processed successfully")
            return result_text
            
        except Exception as e:
            log.error(f"Failed to handle user message: {e}", exc_info=True)
            return f"❌ Failed to process message: {str(e)}"
    
    def create_session_aware_create_mr_tool(self, session_id: str, project_id: str):
        """Create a session-aware merge request creation tool"""
        
        # Get create_merge_request from tool registry
        gitlab_tools = tool_registry.get_tools_for_category("gitlab")
        create_merge_request = None
        for tool_obj in gitlab_tools:
            if hasattr(tool_obj, '__name__') and tool_obj.__name__ == 'create_merge_request':
                create_merge_request = tool_obj
                break
        
        if not create_merge_request:
            # Fallback: import directly if not found in registry
            from tools.gitlab import create_merge_request
        
        @tool
        async def create_merge_request_for_session(
            title: str,
            description: str,
            files: Dict[str, Any],
            target_branch: str = "main",
            update_mode: bool = False
        ) -> Dict[str, Any]:
            """Create or update a merge request with file changes for this session
            
            Args:
                title: MR title
                description: MR description
                files: Dict with 'updates' and 'creates' keys, each containing file paths and content
                target_branch: Target branch (default: main)
                update_mode: If True, commits to existing branch without creating it
            
            Returns:
                Dictionary with MR details or error information
            """
            # Generate branch name using the session context
            from utils.branch_naming import generate_branch_name
            try:
                source_branch = generate_branch_name(session_id, "pipeline")
                log.info(f"Generated branch name: {source_branch} for session {session_id}")
            except Exception as e:
                log.error(f"Failed to generate branch name for session {session_id}: {e}")
                return {"error": f"Invalid session ID format: {e}"}
            
            # Call the original tool with session context
            return await create_merge_request(
                title=title,
                description=description,
                files=files,
                project_id=project_id,
                source_branch=source_branch,
                target_branch=target_branch,
                update_mode=update_mode
            )
        
        return create_merge_request_for_session

    def extract_text_from_response(self, response):
        """Extract text from any response format"""
        if isinstance(response, str):
            return response
        
        # Handle Strands agent response with message attribute
        if hasattr(response, 'message'):
            message = response.message
            
            # Handle nested structure like {'role': 'assistant', 'content': [{'text': '...'}]}
            if isinstance(message, dict):
                if 'content' in message:
                    content = message['content']
                    if isinstance(content, list) and len(content) > 0:
                        first_item = content[0]
                        if isinstance(first_item, dict) and 'text' in first_item:
                            return first_item['text']
                        else:
                            return str(first_item)
                    elif isinstance(content, str):
                        return content
                elif 'text' in message:
                    return message['text']
                else:
                    return str(message)
            else:
                return str(message)
        
        if hasattr(response, 'content'):
            return str(response.content)
        
        # Handle dict with content array (direct dict response)
        if isinstance(response, dict):
            if "content" in response:
                content = response["content"]
                if isinstance(content, list) and len(content) > 0:
                    first_item = content[0]
                    if isinstance(first_item, dict) and 'text' in first_item:
                        return first_item['text']
                    else:
                        return str(first_item)
                return str(content)
            elif "text" in response:
                return response["text"]
            elif "message" in response:
                return str(response["message"])
        
        return str(response)

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

        # Add the analysis result as an assistant message to conversation history
        await self._session_manager.add_message(session_id, "assistant", result_text)

        log.info(f"Stored analysis data with {len(code_blocks)} code blocks")


# Backward compatibility alias
PipelineAnalysisAgent = PipelineAgent

# Global instance for imports
pipeline_agent = PipelineAgent()
