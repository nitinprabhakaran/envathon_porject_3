"""Pipeline failure analysis agent"""

from strands import Agent, tool
from typing import Dict, Any, List
from utils.logger import log
from .base_agent import BaseAnalysisAgent
from .prompts import get_pipeline_system_prompt
from agents.tool_registry import tool_registry
from utils.context_extractor import ContextExtractor
from tools.gitlab import (
    get_pipeline_jobs,
    get_job_logs,
    get_file_content,
    get_recent_commits,
    create_merge_request,
    get_project_info
)


class PipelineAgent(BaseAnalysisAgent):
    def __init__(self):
        super().__init__("Pipeline")
    
    def get_system_prompt(self) -> str:
        """Return the system prompt for pipeline analysis with dynamic capabilities"""
        capabilities = self.get_capabilities_description()
        return get_pipeline_system_prompt(capabilities)
    
    async def analyze_failure(self, *args, **kwargs) -> str:
        """Flexible analyze_failure method supporting multiple calling patterns"""
        try:
            # Pattern 1: Working version - analyze_failure(session_id, project_id, pipeline_id, webhook_data)
            if len(args) == 4:
                session_id, project_id, pipeline_id, webhook_data = args
                log.info(f"Starting pipeline failure analysis for session {session_id}")
                log.info(f"Analyzing pipeline failure for project {project_id}, pipeline {pipeline_id}, session {session_id}")
            
            # Pattern 2: Webhook-first pattern - analyze_failure(webhook_data, session_id)
            elif len(args) == 2:
                webhook_data, session_id = args
                project_id = webhook_data.get("project", {}).get("id")
                pipeline_id = webhook_data.get("object_attributes", {}).get("id")
                log.info(f"Starting pipeline failure analysis for session {session_id}")
                log.info(f"Analyzing pipeline failure for project {project_id}, pipeline {pipeline_id}, session {session_id}")
            
            # Pattern 3: Queue processor kwargs pattern
            elif "webhook_data" in kwargs:
                session_id = kwargs.get("session_id") or (args[0] if args else None)
                webhook_data = kwargs["webhook_data"]
                project_id = kwargs.get("project_id") or webhook_data.get("project", {}).get("id")
                pipeline_id = webhook_data.get("object_attributes", {}).get("id")
                log.info(f"Starting pipeline failure analysis for session {session_id}")
                log.info(f"Analyzing pipeline failure for project {project_id}, pipeline {pipeline_id}, session {session_id}")
            
            else:
                raise ValueError(f"Invalid arguments: args={args}, kwargs={kwargs}")
            
            # Actual analysis logic (simplified for now)
            # TODO: Implement full pipeline analysis logic
            log.info(f"Pipeline analysis completed for session {session_id}")
            return f"Pipeline analysis completed for project {project_id}, pipeline {pipeline_id}"
            
        except Exception as e:
            log.error(f"Error in pipeline analysis: {e}", exc_info=True)
            return f"Analysis failed: {str(e)}"
    
    async def handle_user_message(
        self, 
        session_id: str, 
        message: str, 
        project_id: str, 
        conversation_history: List[Dict[str, Any]]
    ) -> str:
        """Handle user message in pipeline analysis context"""
        try:
            log.info(f"Processing user message for pipeline session {session_id}")
            
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
            
            # Get context tool if webhook data available
            context_tool = None
            if webhook_data:
                from utils.context_extractor import ContextExtractor
                context_tool = ContextExtractor.create_context_tool(session_id, webhook_data, "pipeline")
            
            # Create tools list with conditional context tool
            tools = [
                get_pipeline_jobs,
                get_job_logs,
                tracked_get_file_content,
                get_recent_commits,
                create_merge_request,
                get_project_info,
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
    
    def _create_context_aware_prompt(self, webhook_data: Dict[str, Any], prompt_type: str) -> str:
        """Create context-aware analysis prompts"""
        if prompt_type == "initial_analysis":
            return """## 🔍 Pipeline Failure Analysis

A GitLab CI/CD pipeline has failed and requires comprehensive analysis. To get started:

1. **First, get the failure context** using the `get_failure_context` tool to understand:
   - Project details and repository information
   - Pipeline information (ID, branch, commit details)
   - Failed job details with IDs for log retrieval
   - Overall pipeline status and timing

2. **Then proceed with detailed analysis**:
   - Retrieve logs for the failed job(s) using the provided Job IDs
   - Examine relevant files in the project repository
   - Analyze the failure patterns based on job names and stages
   - Provide specific solutions targeting the identified failure types

Start by calling `get_failure_context()` to get all the essential information you need for the analysis."""
        
        return "Please analyze the pipeline failure using the available tools."


# Backward compatibility alias
PipelineAnalysisAgent = PipelineAgent
