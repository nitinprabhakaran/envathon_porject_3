from strands_agents import Agent, Tool
from anthropic import Anthropic
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
import json

from .tools import (
    analyze_pipeline_logs,
    extract_error_signature,
    intelligent_log_truncation,
    get_session_context,
    update_session_state,
    get_relevant_code_context,
    request_additional_context,
    get_shared_pipeline_context,
    trace_pipeline_inheritance,
    get_cicd_variables,
    search_similar_errors,
    store_successful_fix,
    validate_fix_suggestion
)
from .prompts import SYSTEM_PROMPT
from db.session_manager import SessionManager
from vector.qdrant_client import QdrantManager

class CICDFailureAgent:
    def __init__(self):
        self.anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.session_manager = SessionManager()
        self.qdrant_manager = QdrantManager()
        
        # Initialize the Strands agent with tools
        self.agent = Agent(
            name="cicd-failure-agent",
            model="claude-4-sonnet",
            instructions=SYSTEM_PROMPT,
            tools=self._get_tools()
        )
    
    def _get_tools(self) -> List[Tool]:
        """Register all tools with the agent"""
        return [
            Tool(func=analyze_pipeline_logs),
            Tool(func=extract_error_signature),
            Tool(func=intelligent_log_truncation),
            Tool(func=get_session_context),
            Tool(func=update_session_state),
            Tool(func=get_relevant_code_context),
            Tool(func=request_additional_context),
            Tool(func=get_shared_pipeline_context),
            Tool(func=trace_pipeline_inheritance),
            Tool(func=get_cicd_variables),
            Tool(func=search_similar_errors),
            Tool(func=store_successful_fix),
            Tool(func=validate_fix_suggestion),
        ]
    
    async def analyze_failure(
        self,
        session_id: str,
        webhook_data: Dict[str, Any],
        mcp_manager: Any
    ) -> Dict[str, Any]:
        """Main entry point for analyzing pipeline failures"""
        
        # Create or get session
        session = await self.session_manager.create_or_get_session(
            session_id,
            webhook_data["project"]["id"],
            webhook_data["object_attributes"]["id"],
            webhook_data.get("commit", {}).get("sha")
        )
        
        # Extract failure context
        failure_context = {
            "project_name": webhook_data["project"]["name"],
            "pipeline_id": webhook_data["object_attributes"]["id"],
            "failed_stage": self._extract_failed_stage(webhook_data),
            "commit_message": webhook_data.get("commit", {}).get("message", ""),
            "commit_author": webhook_data.get("commit", {}).get("author", {}).get("name", ""),
            "pipeline_url": webhook_data["object_attributes"]["url"]
        }
        
        # Add MCP manager to context for tool access
        self.agent.context["mcp_manager"] = mcp_manager
        self.agent.context["session_id"] = session_id
        self.agent.context["project_id"] = webhook_data["project"]["id"]
        
        # Run the agent
        try:
            response = await self.agent.run(
                f"""Analyze this CI/CD pipeline failure and provide actionable recommendations:
                
                Session ID: {session_id}
                Project: {failure_context['project_name']}
                Pipeline: {failure_context['pipeline_id']}
                Failed Stage: {failure_context['failed_stage']}
                Commit: {failure_context['commit_message']}
                
                Please:
                1. First check session context for any previous conversation
                2. Use GitLab MCP tools to get pipeline details and logs
                3. Use SonarQube MCP to check for quality issues
                4. Search for similar historical errors
                5. Provide specific, actionable fixes with confidence scores
                6. Format response for UI cards with action buttons
                """
            )
            
            # Update session with conversation
            await self.session_manager.update_conversation(
                session_id,
                {
                    "role": "assistant",
                    "content": response.content,
                    "tools_used": response.tools_used,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
            return {
                "session_id": session_id,
                "analysis": response.content,
                "cards": self._format_response_cards(response.content),
                "confidence": response.metadata.get("confidence", 0.7),
                "tools_used": response.tools_used
            }
            
        except Exception as e:
            return {
                "session_id": session_id,
                "error": str(e),
                "cards": [{
                    "type": "error",
                    "title": "Analysis Failed",
                    "content": f"Failed to analyze pipeline: {str(e)}",
                    "actions": [{"label": "Retry", "action": "retry_analysis"}]
                }]
            }
    
    async def continue_conversation(
        self,
        session_id: str,
        user_message: str,
        mcp_manager: Any
    ) -> Dict[str, Any]:
        """Continue an existing conversation"""
        
        # Get session context
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Add to conversation history
        await self.session_manager.update_conversation(
            session_id,
            {
                "role": "user",
                "content": user_message,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        # Set context
        self.agent.context["mcp_manager"] = mcp_manager
        self.agent.context["session_id"] = session_id
        self.agent.context["project_id"] = session["project_id"]
        
        # Get full conversation history
        conversation_history = session.get("conversation_history", [])
        
        # Run agent with context
        response = await self.agent.run(
            f"""Continue the conversation for session {session_id}.
            
            User message: {user_message}
            
            Previous conversation context is available via get_session_context tool.
            Consider what was already discussed and tried.
            """
        )
        
        # Update session
        await self.session_manager.update_conversation(
            session_id,
            {
                "role": "assistant",
                "content": response.content,
                "tools_used": response.tools_used,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        return {
            "session_id": session_id,
            "response": response.content,
            "cards": self._format_response_cards(response.content),
            "tools_used": response.tools_used
        }
    
    def _extract_failed_stage(self, webhook_data: Dict[str, Any]) -> str:
        """Extract the failed stage from webhook data"""
        # Implementation depends on GitLab webhook structure
        builds = webhook_data.get("builds", [])
        for build in builds:
            if build.get("status") == "failed":
                return build.get("stage", "unknown")
        return "unknown"
    
    def _format_response_cards(self, content: str) -> List[Dict[str, Any]]:
        """Format agent response into UI cards"""
        # This is a simplified version - in production, parse the agent's structured output
        cards = []
        
        # Try to parse structured response from agent
        try:
            # Agent should return JSON blocks for cards
            import re
            card_blocks = re.findall(r'```json:card\n(.*?)\n```', content, re.DOTALL)
            for block in card_blocks:
                cards.append(json.loads(block))
        except:
            # Fallback to simple text card
            cards.append({
                "type": "analysis",
                "title": "Pipeline Analysis",
                "content": content,
                "actions": []
            })
        
        return cards