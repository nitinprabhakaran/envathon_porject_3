"""Pipeline Failure Analysis Agent using Strands SDK and optimized patterns"""
from strands import Agent, tool
from typing import Dict, Any, List, Optional
import asyncio
import json

from .base_agent import BaseAnalysisAgent
from .prompts import PIPELINE_SYSTEM_PROMPT, get_conversation_continuation_prompt, get_webhook_analysis_prompt
from utils.logger import log
from tools.gitlab import (
    get_pipeline_info, get_pipeline_logs, 
    create_merge_request, search_files
)


class PipelineAnalysisAgent(BaseAnalysisAgent):
    """Specialized agent for analyzing GitLab CI/CD pipeline failures"""
    
    def __init__(self):
        super().__init__("Pipeline")
    
    def get_system_prompt(self) -> str:
        """Return the system prompt for pipeline analysis"""
        return PIPELINE_SYSTEM_PROMPT
    
    async def analyze_failure(
        self, 
        session_id: str, 
        webhook_data: Dict[str, Any], 
        project_id: str
    ) -> str:
        """Analyze pipeline failure from webhook data"""
        try:
            log.info(f"Starting pipeline failure analysis for session {session_id}")
            
            # Check iteration limit
            limit_message = await self.check_iteration_limit(session_id)
            if limit_message:
                return limit_message
            
            # Store webhook data
            await self._session_manager.update_session_metadata(
                session_id, {"webhook_data": webhook_data}
            )
            
            # Create tools for this session
            tracked_file_tool = self.create_tracked_file_tool(session_id)
            session_data_tool = self.create_session_data_tool(session_id)
            
            # Create agent with proper tools
            agent = Agent(
                model=self.model,
                system_prompt=self.get_system_prompt(),
                tools=[
                    get_pipeline_info,
                    get_pipeline_logs,
                    tracked_file_tool,
                    create_merge_request,
                    search_files,
                    session_data_tool
                ]
            )
            
            # Generate analysis prompt
            analysis_prompt = get_webhook_analysis_prompt(webhook_data, "pipeline")
            
            # Run analysis
            response = await agent.run(analysis_prompt)
            result_text = self.extract_text_from_response(response)
            
            # Store analysis data
            await self.store_analysis_data(session_id, result_text)
            
            # Track merge request if created
            result_text = await self.track_merge_request(
                session_id, result_text, project_id, "merge_request" in result_text.lower()
            )
            
            log.info("Pipeline analysis completed successfully")
            return result_text
            
        except Exception as e:
            log.error(f"Pipeline analysis failed: {e}", exc_info=True)
            return f"❌ Analysis failed: {str(e)}"
    
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
            
            # Create tools for this session
            tracked_file_tool = self.create_tracked_file_tool(session_id, current_fix_branch)
            session_data_tool = self.create_session_data_tool(session_id)
            
            # Create agent with proper tools
            agent = Agent(
                model=self.model,
                system_prompt=self.get_system_prompt(),
                tools=[
                    get_pipeline_info,
                    get_pipeline_logs,
                    tracked_file_tool,
                    create_merge_request,
                    search_files,
                    session_data_tool
                ]
            )
            
            # Format conversation context
            context = self.format_conversation_history(conversation_history)
            continuation_prompt = get_conversation_continuation_prompt("pipeline", context)
            
            # Combine prompts
            full_prompt = f"{continuation_prompt}\n\n## User Request\n{message}"
            
            # Run conversation
            response = await agent.run(full_prompt)
            result_text = self.extract_text_from_response(response)
            
            # Store analysis data if this was an analysis response
            if any(keyword in result_text.lower() for keyword in ["analysis", "failure", "error", "issue"]):
                await self.store_analysis_data(session_id, result_text)
            
            # Track merge request if created
            result_text = await self.track_merge_request(
                session_id, result_text, project_id, "merge_request" in message.lower()
            )
            
            log.info("User message processed successfully")
            return result_text
            
        except Exception as e:
            log.error(f"Failed to handle user message: {e}", exc_info=True)
            return f"❌ Failed to process message: {str(e)}"
