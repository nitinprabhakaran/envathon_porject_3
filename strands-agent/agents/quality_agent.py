"""SonarQube quality analysis agent"""

from strands import Agent, tool
from typing import Dict, Any, List
import json
from utils.logger import log
from .base_agent import BaseAnalysisAgent
from .prompts import (
    get_quality_system_prompt, 
    get_quality_failure_analysis_prompt,
    get_quality_comprehensive_analysis_prompt,
    get_quality_fallback_analysis_prompt
)
from tools.tool_registry import tool_registry
from utils.context_extractor import ContextExtractor


class QualityAgent(BaseAnalysisAgent):
    def __init__(self):
        super().__init__("Quality")
    
    def get_system_prompt(self) -> str:
        """Return the system prompt for quality analysis with dynamic capabilities"""
        capabilities = self.get_capabilities_description()
        return get_quality_system_prompt(capabilities)
    
    def create_session_aware_create_mr_tool(self, session_id: str, project_id: str):
        """Create a session-aware merge request creation tool that uses tracked files"""
        
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
            
            This function will automatically integrate tracked files from the session if no files are provided.
            
            Args:
                title: MR title
                description: MR description
                files: Dict with 'updates' and 'creates' keys, each containing file paths and content.
                       If empty, will use tracked files from the session.
                target_branch: Target branch (default: main)
                update_mode: If True, commits to existing branch without creating it
            
            Returns:
                Dictionary with MR details or error information
            """
            try:
                # If no files provided, get tracked files from session
                if not files or (not files.get("updates") and not files.get("creates")):
                    log.info(f"No files provided, retrieving tracked files for session {session_id}")
                    tracked_files = await self._session_manager.get_tracked_files(session_id)
                    
                    if tracked_files:
                        log.info(f"Found {len(tracked_files)} tracked files for session {session_id}")
                        files = {"updates": {}, "creates": {}}
                        
                        for file_path, file_data in tracked_files.items():
                            if file_data.get("status") == "success" and file_data.get("tracked_content"):
                                files["updates"][file_path] = file_data["tracked_content"]
                                log.info(f"Added tracked file to MR: {file_path}")
                    else:
                        log.warning(f"No tracked files found for session {session_id}")
                        return {
                            "error": "No files provided and no tracked files found in session. Please retrieve and analyze files first.",
                            "tracked_files_count": 0
                        }
                
                # Generate branch name using the session context
                from utils.branch_naming import generate_branch_name
                try:
                    source_branch = generate_branch_name(session_id, "quality")
                    log.info(f"Generated branch name: {source_branch} for session {session_id}")
                except Exception as e:
                    log.error(f"Failed to generate branch name for session {session_id}: {e}")
                    return {"error": f"Invalid session ID format: {e}"}
                
                # Create fix attempt record
                fix_attempts = await self._session_manager.get_fix_attempts(session_id)
                attempt_number = await self._session_manager.create_fix_attempt(
                    session_id, 
                    source_branch, 
                    list(files.get("updates", {}).keys()) + list(files.get("creates", {}).keys())
                )
                
                log.info(f"Created fix attempt #{attempt_number} for session {session_id}")
                
                # Call the original tool with session context
                result = await create_merge_request(
                    title=title,
                    description=description,
                    files=files,
                    project_id=project_id,
                    source_branch=source_branch,
                    target_branch=target_branch,
                    update_mode=update_mode
                )
                
                # Update fix attempt with MR details if successful
                if result.get("web_url"):
                    await self._session_manager.update_fix_attempt(
                        session_id,
                        attempt_number,
                        "pending",  # Will be updated by webhook when pipeline runs
                        result.get("id"),
                        result.get("web_url")
                    )
                    
                    # Store MR URL in session for UI
                    session_data = await self._session_manager.get_session(session_id)
                    if session_data:
                        await self._session_manager.update_session_metadata(
                            session_id,
                            {"merge_request_url": result.get("web_url")}
                        )
                
                return result
                
            except Exception as e:
                log.error(f"Error in session-aware MR creation: {e}", exc_info=True)
                return {"error": str(e)}
        
        return create_merge_request_for_session
    
    async def analyze_failure(self, *args, **kwargs) -> str:
        """Analyze quality gate failure with context from webhook data - flexible signature"""
        try:
            # Handle both calling patterns
            if len(args) == 2 and not kwargs:
                # New pattern: analyze_failure(webhook_data, session_id)
                webhook_data, session_id = args
                # Extract project key from webhook data
                project_key = webhook_data.get("project", {}).get("path_with_namespace", "").replace("/", "_")
                gitlab_project_id = webhook_data.get("project", {}).get("id")
            elif len(args) == 4:
                # Working pattern: analyze_failure(session_id, project_key, gitlab_project_id, webhook_data)
                session_id, project_key, gitlab_project_id, webhook_data = args
            elif 'session_id' in kwargs and 'webhook_data' in kwargs:
                # Queue processor pattern: analyze_failure(session_id=..., webhook_data=..., project_id=...)
                session_id = kwargs.get('session_id')
                webhook_data = kwargs.get('webhook_data', {})
                project_key = kwargs.get('project_id')
                gitlab_project_id = webhook_data.get("project", {}).get("id")
                
                # If project_key is None, extract from webhook_data
                if not project_key:
                    project_key = webhook_data.get("project", {}).get("path_with_namespace", "").replace("/", "_")
                    # Also try SonarQube project key format
                    if not project_key and 'projectKey' in webhook_data:
                        project_key = webhook_data['projectKey']
            else:
                raise ValueError(f"Unsupported arguments: args={args}, kwargs={kwargs}")
            
            log.info(f"Starting quality analysis for session {session_id}")
            log.info(f"Analyzing quality issues for project {project_key}, session {session_id}")
            
            # Check if issues are already fetched
            total_issues = 0
            if 'quality_metrics' in webhook_data:
                metrics = webhook_data['quality_metrics']
                total_issues = metrics.get('total_issues', 0)
            
            # Create analysis prompt - WORKING PATTERN
            # Create analysis prompt - enhanced to handle various webhook data formats
            sonar_project_key = project_key
            if not sonar_project_key:
                # Try various ways to extract SonarQube project key
                sonar_project_key = (
                    webhook_data.get('projectKey') or 
                    webhook_data.get('project', {}).get('key') or
                    webhook_data.get('project', {}).get('path_with_namespace', '').replace('/', '_') or
                    'quality-demo'  # Default fallback
                )
            
            quality_gate_status = webhook_data.get('qualityGate', {}).get('status', 'ERROR')
            failed_conditions = webhook_data.get('qualityGate', {}).get('conditions', [])
            
            # Create analysis prompt using centralized prompts
            prompt = get_quality_failure_analysis_prompt(sonar_project_key, gitlab_project_id, webhook_data)

            # Get tools for quality analysis
            base_tool_objects = tool_registry.get_tools_for_agent("quality", [])
            
            # Create context tool with comprehensive project information
            @tool
            async def get_quality_context() -> str:
                """Get comprehensive context about this quality gate failure"""
                return f"""# Quality Gate Failure Context

## Project Information
- **SonarQube Project Key**: {sonar_project_key}
- **GitLab Project ID**: {gitlab_project_id}
- **Quality Gate Status**: {webhook_data.get('qualityGate', {}).get('status', 'ERROR')}

## Failed Conditions
{json.dumps(webhook_data.get('qualityGate', {}).get('conditions', []), indent=2)}

## Session Information
- **Session ID**: {session_id}
- **Analysis Type**: Quality Gate Failure

## Available Actions
You have access to SonarQube tools to:
1. Get detailed project metrics
2. Get all project issues by type
3. Get specific issue details
4. Get rule descriptions for violations

Focus on addressing the failed quality gate conditions first."""

            # Combine all tools
            all_tool_objects = base_tool_objects + [get_quality_context]
            
            # Filter out raw create_merge_request and replace with session-aware version
            filtered_tools = []
            for tool_obj in all_tool_objects:
                if hasattr(tool_obj, '__name__') and tool_obj.__name__ == 'create_merge_request':
                    # Replace with session-aware version
                    filtered_tools.append(self.create_session_aware_create_mr_tool(session_id))
                else:
                    filtered_tools.append(tool_obj)
            
            # Create agent with enhanced context
            agent = Agent(
                model=self.model,
                system_prompt=get_quality_system_prompt(),
                tools=filtered_tools
            )
            
            # Create wrapped get_file_content that stores files immediately - WORKING PATTERN
            # Get the original get_file_content from tools
            gitlab_tools = tool_registry.get_tools_for_category("gitlab")
            get_file_content = None
            for tool_obj in gitlab_tools:
                if hasattr(tool_obj, '__name__') and tool_obj.__name__ == 'get_file_content':
                    get_file_content = tool_obj
                    break
            
            if not get_file_content:
                # Fallback: import directly if not found in registry
                from tools.gitlab import get_file_content
            
            @tool
            async def tracked_get_file_content(file_path: str, project_id: str, ref: str = "HEAD") -> str:
                """Get content of a file from GitLab repository"""
                result = await get_file_content(file_path, project_id, ref)
                
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
            
            # Create agent for analysis - WORKING PATTERN
            agent = Agent(
                model=self.model,
                system_prompt=get_quality_system_prompt(),
                tools=all_tool_objects
            )
            
            result = await agent.invoke_async(prompt)
            log.info(f"Quality analysis complete for session {session_id}")
            
            # Extract text from result - WORKING PATTERN
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
            
            # Store analysis result in session
            await self._session_manager.update_session_metadata(
                session_id, 
                {"analysis_result": result_text}
            )
            
            # Add the analysis result as an assistant message to conversation history
            await self._session_manager.add_message(session_id, "assistant", result_text)
            
            return result_text
            
        except Exception as e:
            log.error(f"Error in quality analysis: {e}", exc_info=True)
            return f"Analysis failed: {str(e)}"
    
    async def handle_user_message(
        self, 
        session_id: str, 
        message: str, 
        conversation_history: List[Dict[str, Any]],
        context: Any
    ) -> str:
        """Handle user message in quality analysis context"""
        try:
            log.info(f"Processing user message for quality session {session_id}")
            
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
                context_tool = ContextExtractor.create_context_tool(session_id, webhook_data, "quality")
            
            # Get tools from registry - SonarQube and GitLab tools
            sonarqube_tools = tool_registry.get_tools_for_category("sonarqube")
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
            
            # Create tools list with session-specific tools
            tools = sonarqube_tools + [
                tracked_get_file_content,
                session_aware_create_mr,
                session_data_tool
            ]
            
            # Add specific GitLab tools needed for quality agent (excluding create_merge_request)
            for tool in gitlab_tools:
                if hasattr(tool, '__name__') and tool.__name__ in ['get_project_info']:
                    tools.append(tool)
                elif hasattr(tool, 'name') and tool.name in ['get_project_info', 'get_file_content', 'get_job_logs', 'get_merge_request_details', 'get_pipeline_jobs', 'get_recent_commits']:
                    tools.append(tool)
            
            if context_tool:
                tools.append(context_tool)
            
            # Create agent
            agent = Agent(
                model=self.model,
                system_prompt=self.get_system_prompt(),
                tools=tools
            )
            
            # Format conversation context
            context_str = self.format_conversation_history(conversation_history)
            from .prompts import get_conversation_continuation_prompt
            continuation_prompt = get_conversation_continuation_prompt("quality", context_str)
            
            # Add explicit project context information
            project_context = f"""
## Current Session Context
- **Project ID**: {project_id}
- **Session Type**: Quality Analysis
- **Available Tools**: get_failure_context, get_session_data, get_file_content_tracked, create_merge_request
- **Previous Analysis**: Available via get_session_data tool
"""
            
            # Combine prompts
            full_prompt = f"{continuation_prompt}\n{project_context}\n\n## User Request\n{message}"            # Run conversation
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
    
    # Alias for compatibility
    async def analyze_quality_issues(self, session_id: str, project_key: str, gitlab_project_id: str, webhook_data: Dict[str, Any]) -> str:
        """Analyze quality issues - working version signature with enhanced data handling"""
        try:
            log.info(f"Starting quality analysis for session {session_id}")
            log.info(f"Analyzing quality issues for project {project_key}, session {session_id}")
            
            # Check if we have enhanced SonarQube data from queue processor
            sonarqube_data = webhook_data.get("sonarqube_data", {})
            quality_gate = webhook_data.get("qualityGate", {})
            
            if sonarqube_data:
                # We have pre-fetched SonarQube data - use it directly for analysis
                total_issues = sonarqube_data.get("total_issues", 0)
                bugs = sonarqube_data.get("bugs", [])
                vulnerabilities = sonarqube_data.get("vulnerabilities", [])
                code_smells = sonarqube_data.get("code_smells", [])
                
                log.info(f"Using pre-fetched SonarQube data: {total_issues} total issues")
                
                # Create comprehensive analysis prompt using centralized prompts
                prompt = get_quality_comprehensive_analysis_prompt(project_key, gitlab_project_id, webhook_data, sonarqube_data)
            
            else:
                # Fallback to basic analysis with available webhook data
                prompt = get_quality_fallback_analysis_prompt(project_key, gitlab_project_id, webhook_data)
            
            # Get tools for analysis (GitLab tools for file access)
            base_tools = tool_registry.get_tools_for_agent("quality", [])
            
            # Add SonarQube tools if we need to fetch additional data
            if not sonarqube_data:
                sonarqube_tools = tool_registry.get_tools_for_category("sonarqube")
                base_tools.extend(sonarqube_tools)
            
            # Create agent with tools
            agent = Agent(
                model=self.model,
                system_prompt=self.get_system_prompt(),
                tools=base_tools
            )
            
            result = await agent.invoke_async(prompt)
            log.info(f"Quality analysis complete for session {session_id}")
            
            # Debug: Log the actual result format
            log.info(f"Agent result type: {type(result)}")
            if hasattr(result, '__dict__'):
                log.info(f"Agent result attributes: {list(result.__dict__.keys())}")
            
            # Try to get the actual content by checking all possible attributes
            result_text = ""
            extraction_method = "unknown"
            
            # Check various ways to extract the text from AgentResult
            for attr_name in ['text', 'content', 'message', 'response', 'output', 'result']:
                if hasattr(result, attr_name):
                    attr_value = getattr(result, attr_name)
                    log.info(f"Found attribute '{attr_name}': {type(attr_value)} = {str(attr_value)[:100]}...")
                    
                    if isinstance(attr_value, str) and attr_value.strip() and not attr_value.startswith('{'):
                        result_text = attr_value
                        extraction_method = f"result.{attr_name}"
                        break
            
            # If no clean text found, try the more complex extraction
            if not result_text:
                log.info("No direct text attribute found, trying complex extraction...")
                
                # Handle object with message attribute
                if hasattr(result, 'message'):
                    message = result.message
                    log.info(f"result.message is: {type(message)} = {str(message)[:100]}...")
                    
                    if isinstance(message, str) and not message.startswith('{'):
                        result_text = message
                        extraction_method = "result.message (string)"
                    elif isinstance(message, dict):
                        # Handle {'role': 'assistant', 'content': [{'text': '...'}]} structure
                        if 'content' in message:
                            content = message['content']
                            log.info(f"message.content is: {type(content)} = {str(content)[:100]}...")
                            
                            if isinstance(content, list) and len(content) > 0:
                                first_item = content[0]
                                log.info(f"content[0] is: {type(first_item)} = {str(first_item)[:100]}...")
                                
                                if isinstance(first_item, dict) and 'text' in first_item:
                                    result_text = first_item['text']
                                    extraction_method = "result.message['content'][0]['text']"
                                    log.info(f"Successfully extracted text using method: {extraction_method}, length: {len(result_text)}")
                                else:
                                    result_text = str(first_item)
                                    extraction_method = "result.message['content'][0] (string)"
                            elif isinstance(content, str):
                                result_text = content
                                extraction_method = "result.message['content'] (string)"
                        elif 'text' in message:
                            result_text = message['text']
                            extraction_method = "result.message['text']"
                
                # Handle object with content attribute (secondary)
                elif hasattr(result, 'content'):
                    content = result.content
                    if isinstance(content, str) and not content.startswith('{'):
                        result_text = content
                        extraction_method = "result.content (string)"
                    elif isinstance(content, list) and len(content) > 0:
                        # Handle list format: [{'text': '...'}]
                        if isinstance(content[0], dict) and "text" in content[0]:
                            result_text = content[0]["text"]
                            extraction_method = "result.content[0]['text']"
                        else:
                            result_text = str(content[0])
                            extraction_method = "result.content[0] (string)"
                    else:
                        log.info(f"result.content is: {type(content)} = {str(content)[:100]}...")
            
            # If still no result, check if the result is itself a dict or string
            if not result_text:
                log.info("Still no text found, checking result type directly...")
                
                # Handle direct string response
                if isinstance(result, str) and not result.startswith('{'):
                    result_text = result
                    extraction_method = "direct string"
                # Handle dict response formats
                elif isinstance(result, dict):
                    log.info(f"Result is dict with keys: {list(result.keys())}")
                    # Handle agent response format: {'role': 'assistant', 'content': [{'text': '...'}]}
                    if "role" in result and "content" in result:
                        content = result["content"]
                        if isinstance(content, list) and len(content) > 0:
                            if isinstance(content[0], dict) and "text" in content[0]:
                                result_text = content[0]["text"]
                                extraction_method = "dict['content'][0]['text']"
                            else:
                                result_text = str(content[0])
                                extraction_method = "dict['content'][0] (string)"
                        elif isinstance(content, str):
                            result_text = content
                            extraction_method = "dict['content'] (string)"
                    elif "content" in result:
                        content = result["content"]
                        if isinstance(content, list) and len(content) > 0:
                            if isinstance(content[0], dict) and "text" in content[0]:
                                result_text = content[0]["text"]
                                extraction_method = "dict['content'][0]['text']"
                            else:
                                result_text = str(content[0])
                                extraction_method = "dict['content'][0] (string)"
                        else:
                            result_text = str(content)
                            extraction_method = "dict['content'] (fallback)"
                    elif "text" in result:
                        result_text = result["text"]
                        extraction_method = "dict['text']"
                    elif "message" in result:
                        result_text = result["message"]
                        extraction_method = "dict['message']"
            
            # Final fallback - but don't use str() as it might return the dict format
            if not result_text:
                result_text = f"## Extraction Failed\n\nCould not extract text from agent result of type {type(result)}"
                extraction_method = "failed"
            
            log.info(f"Text extraction method: {extraction_method}")
            log.info(f"Extracted result text length: {len(result_text)}")
            log.info(f"Result text preview: {result_text[:200]}...")
            if not result_text or result_text.strip() == "":
                result_text = f"## Quality Analysis Failed\n\nThe analysis did not produce any output. Please check the SonarQube project key '{project_key}' and ensure the project exists in SonarQube."
            
            # Store analysis result in session
            await self._session_manager.update_session_metadata(
                session_id, 
                {"analysis_result": result_text}
            )
            
            # Add the analysis result as an assistant message to conversation history
            await self._session_manager.add_message(session_id, "assistant", result_text)
            
            return result_text
            
        except Exception as e:
            error_msg = f"Analysis failed: {str(e)}"
            log.error(f"Error in quality analysis: {e}", exc_info=True)
            
            # Store error in session
            await self._session_manager.update_session_metadata(
                session_id, 
                {"analysis_error": str(e), "analysis_result": error_msg}
            )
            
            return error_msg


# Backward compatibility alias
QualityAnalysisAgent = QualityAgent

# Global instance for imports
quality_agent = QualityAgent()
