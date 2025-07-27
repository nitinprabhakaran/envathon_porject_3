from typing import Dict, List, Any, Optional
from datetime import datetime
import json
import re
import os
from loguru import logger
import asyncio

from strands import Agent
from strands.models import BedrockModel
from strands.models.anthropic import AnthropicModel
from strands.agent.conversation_manager import SlidingWindowConversationManager

from .prompts import SYSTEM_PROMPT
from db.session_manager import SessionManager
from vector.qdrant_client import QdrantManager

# Import only essential tools for initial analysis
from tools.gitlab_tools import (
    get_pipeline_jobs,
    get_job_logs,
    create_merge_request
)
from tools.analysis_tools import (
    analyze_pipeline_logs,
    extract_error_signature
)
from tools.session_tools import (
    get_session_context,
    search_similar_errors,
    store_successful_fix
)

class CICDFailureAgent:
    def __init__(self):
        self.session_manager = SessionManager()
        self.qdrant_manager = QdrantManager()
        
        # Configure model with optimal settings
        provider = os.getenv("LLM_PROVIDER", "bedrock").lower()
        
        if provider == "bedrock":
            model = BedrockModel(
                model_id=os.getenv("MODEL_ID", "us.anthropic.claude-3-5-sonnet-20241022-v2:0"),
                region=os.getenv("AWS_REGION", "us-west-2"),
                temperature=0.3,
                streaming=True,
                max_tokens=2048,
                top_p=0.8
            )
        elif provider == "anthropic":
            model = AnthropicModel(
                model_id=os.getenv("MODEL_ID", "claude-3-5-sonnet-20241022"),
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                temperature=0.3,
                max_tokens=2048
            )
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")
        
        # Optimize conversation management
        conversation_manager = SlidingWindowConversationManager(
            window_size=10
        )
        
        # Initialize with minimal tools
        self.agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=self._get_minimal_tools(),
            conversation_manager=conversation_manager
        )
    
    def _get_minimal_tools(self) -> List:
        """Get only essential tools for initial analysis"""
        return [
            get_pipeline_jobs,
            get_job_logs,
            analyze_pipeline_logs,
            extract_error_signature,
            search_similar_errors,
            get_session_context,
            create_merge_request
        ]
    
    def _get_extended_tools(self) -> List:
        """Get additional tools for complex cases"""
        from tools.gitlab_tools import (
            get_file_content,
            get_recent_commits,
            add_pipeline_comment
        )
        from tools.context_tools import (
            get_relevant_code_context,
            request_additional_context,
            get_shared_pipeline_context
        )
        from tools.sonarqube_tools import (
            get_project_quality_status,
            get_code_quality_issues
        )
        
        return [
            *self._get_minimal_tools(),
            get_file_content,
            get_recent_commits,
            add_pipeline_comment,
            get_relevant_code_context,
            request_additional_context,
            get_shared_pipeline_context,
            get_project_quality_status,
            get_code_quality_issues,
            store_successful_fix
        ]
    
    async def analyze_failure(
        self,
        session_id: str,
        webhook_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Optimized failure analysis with minimal tool calls"""
        start_time = datetime.utcnow()
        logger.info(f"Starting optimized analysis for session {session_id}")
        
        # Create or get session
        try:
            session = await self.session_manager.create_or_get_session(
                session_id,
                str(webhook_data["project"]["id"]),
                str(webhook_data["object_attributes"]["id"]),
                webhook_data.get("commit", {}).get("sha")
            )
        except Exception as e:
            logger.error(f"Failed to create/get session: {e}")
            raise
        
        # Extract failure context
        failure_context = {
            "project_name": webhook_data["project"]["name"],
            "pipeline_id": webhook_data["object_attributes"]["id"],
            "failed_stage": self._extract_failed_stage(webhook_data),
            "job_name": self._extract_failed_job_name(webhook_data),
            "branch": webhook_data["object_attributes"]["ref"],
            "pipeline_url": webhook_data["object_attributes"]["url"]
        }
        
        # Store context in agent's session state
        self.agent.session_state = {
            "session_id": session_id,
            "project_id": str(webhook_data["project"]["id"]),
            "pipeline_id": str(webhook_data["object_attributes"]["id"]),
            "failure_context": failure_context
        }
        
        # Optimized prompt for minimal tool usage
        prompt = f"""Analyze this pipeline failure:

Pipeline #{failure_context['pipeline_id']} failed in {failure_context['failed_stage']} stage
Job: {failure_context['job_name']}
Project: {failure_context['project_name']} (ID: {webhook_data['project']['id']})

Use tools to investigate and provide a solution."""
        
        try:
            # Use streaming for better UX
            response_text = ""
            async for event in self.agent.stream_async(prompt):
                if "data" in event:
                    response_text += event["data"]
            
            # Store response
            await self.session_manager.update_conversation(
                session_id,
                {
                    "role": "assistant",
                    "content": response_text,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"Analysis completed in {duration:.2f}s")
            
            return {
                "session_id": session_id,
                "analysis": response_text,
                "duration_seconds": duration
            }
            
        except Exception as e:
            logger.error(f"Analysis failed: {e}", exc_info=True)
            
            await self.session_manager.update_conversation(
                session_id,
                {
                    "role": "assistant",
                    "content": f"Error: {str(e)}",
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
            return {
                "session_id": session_id,
                "error": str(e)
            }
    
    async def continue_conversation(
        self,
        session_id: str,
        user_message: str
    ) -> Dict[str, Any]:
        """Continue conversation"""
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise ValueError("Session not found")
        
        # Add user message
        await self.session_manager.update_conversation(
            session_id,
            {
                "role": "user",
                "content": user_message,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        # Check if we need extended tools
        needs_extended = any(keyword in user_message.lower() for keyword in [
            "quality", "sonar", "file", "code", "commit", "merge request"
        ])
        
        if needs_extended and len(self.agent.tools) < 10:
            logger.info("Loading extended tools for complex request")
            self.agent.tools = self._get_extended_tools()
        
        # Set context
        self.agent.session_state = {
            "session_id": session_id,
            "project_id": str(session["project_id"]),
            "pipeline_id": str(session.get("pipeline_id", ""))
        }
        
        # Generate response
        response_text = ""
        async for event in self.agent.stream_async(user_message):
            if "data" in event:
                response_text += event["data"]
        
        await self.session_manager.update_conversation(
            session_id,
            {
                "role": "assistant",
                "content": response_text,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        return {
            "session_id": session_id,
            "response": response_text
        }
    
    def _extract_failed_stage(self, webhook_data: Dict[str, Any]) -> str:
        """Extract the failed stage from webhook data"""
        builds = webhook_data.get("builds", [])
        for build in builds:
            if build.get("status") == "failed":
                return build.get("stage", "unknown")
        return "unknown"
    
    def _extract_failed_job_name(self, webhook_data: Dict[str, Any]) -> str:
        """Extract the failed job name from webhook data"""
        builds = webhook_data.get("builds", [])
        for build in builds:
            if build.get("status") == "failed":
                return build.get("name", "unknown")
        return "unknown"