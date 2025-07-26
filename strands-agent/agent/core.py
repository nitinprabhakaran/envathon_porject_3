from typing import Dict, List, Any, Optional
from datetime import datetime
import json
import re
import os
from loguru import logger

from strands import Agent
from strands.models import BedrockModel
from strands.models.anthropic import AnthropicModel

from .prompts import SYSTEM_PROMPT
from db.session_manager import SessionManager
from vector.qdrant_client import QdrantManager

# Import all tools
from tools.gitlab_tools import (
    get_pipeline_details,
    get_pipeline_jobs,
    get_job_logs,
    get_file_content,
    get_recent_commits,
    create_merge_request,
    add_pipeline_comment
)
from tools.sonarqube_tools import (
    get_project_quality_status,
    get_code_quality_issues,
    get_security_vulnerabilities
)
from tools.analysis_tools import (
    analyze_pipeline_logs,
    extract_error_signature,
    intelligent_log_truncation
)
from tools.context_tools import (
    get_relevant_code_context,
    request_additional_context,
    get_shared_pipeline_context,
    trace_pipeline_inheritance,
    get_cicd_variables
)
from tools.session_tools import (
    get_session_context,
    update_session_state,
    search_similar_errors,
    store_successful_fix,
    validate_fix_suggestion
)

class CICDFailureAgent:
    def __init__(self):
        self.session_manager = SessionManager()
        self.qdrant_manager = QdrantManager()
        
        # Configure model based on provider
        provider = os.getenv("LLM_PROVIDER", "bedrock").lower()
        
        if provider == "bedrock":
            model = BedrockModel(
                model_id=os.getenv("MODEL_ID", "us.anthropic.claude-3-5-sonnet-20241022-v2:0"),
                region=os.getenv("AWS_REGION", "us-west-2"),
                temperature=0.7,
                streaming=False,
                max_tokens=4096
            )
        elif provider == "anthropic":
            model = AnthropicModel(
                model_id=os.getenv("MODEL_ID", "claude-3-5-sonnet-20241022"),
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                temperature=0.7,
                max_tokens=8192
            )
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")
        
        # Initialize Strands agent
        self.agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=self._get_tools()
        )
    
    def _get_tools(self) -> List:
        """Register all tools with the agent"""
        return [
            # GitLab tools
            get_pipeline_details,
            get_pipeline_jobs,
            get_job_logs,
            get_file_content,
            get_recent_commits,
            create_merge_request,
            add_pipeline_comment,
            
            # SonarQube tools
            get_project_quality_status,
            get_code_quality_issues,
            get_security_vulnerabilities,
            
            # Analysis tools
            analyze_pipeline_logs,
            extract_error_signature,
            intelligent_log_truncation,
            
            # Context tools
            get_relevant_code_context,
            request_additional_context,
            get_shared_pipeline_context,
            trace_pipeline_inheritance,
            get_cicd_variables,
            
            # Session tools
            get_session_context,
            update_session_state,
            search_similar_errors,
            store_successful_fix,
            validate_fix_suggestion
        ]
    
    async def analyze_failure(
        self,
        session_id: str,
        webhook_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Main entry point for analyzing pipeline failures"""
        logger.info(f"Starting analysis for session {session_id}")
        logger.debug(f"Webhook data: {json.dumps(webhook_data, indent=2)}")
        
        # Create or get session
        try:
            session = await self.session_manager.create_or_get_session(
                session_id,
                str(webhook_data["project"]["id"]),
                str(webhook_data["object_attributes"]["id"]),
                webhook_data.get("commit", {}).get("sha")
            )
            logger.info(f"Session created/retrieved: {session['id']}")
        except Exception as e:
            logger.error(f"Failed to create/get session: {e}")
            raise
        
        # Extract failure context
        failure_context = {
            "project_name": webhook_data["project"]["name"],
            "pipeline_id": webhook_data["object_attributes"]["id"],
            "failed_stage": self._extract_failed_stage(webhook_data),
            "commit_message": webhook_data.get("commit", {}).get("message", ""),
            "commit_author": webhook_data.get("commit", {}).get("author", {}).get("name", ""),
            "pipeline_url": webhook_data["object_attributes"]["url"],
            "branch": webhook_data["object_attributes"]["ref"], 
            "pipeline_source": webhook_data["object_attributes"]["source"],
            "commit_sha": webhook_data["object_attributes"]["sha"],
            "job_name": self._extract_failed_job_name(webhook_data),
            "merge_request_id": webhook_data.get("merge_request", {}).get("id") if webhook_data.get("merge_request") else None,
        }
        
        logger.info(f"Failure context: {failure_context}")
        
        # Store context in agent's session state
        self.agent.session_state = {
            "session_id": session_id,
            "project_id": str(webhook_data["project"]["id"]),
            "pipeline_id": str(webhook_data["object_attributes"]["id"]),
            "failure_context": failure_context
        }
        
        # Run the agent
        try:
            logger.info("Invoking Strands agent for analysis")
            
            # Create a prompt that includes all context explicitly
            prompt = f"""Analyze this CI/CD pipeline failure and provide actionable recommendations:
                
Session ID: {session_id}
Project ID: {webhook_data['project']['id']}
Project Name: {failure_context['project_name']}
Pipeline ID: {failure_context['pipeline_id']}
Failed Stage: {failure_context['failed_stage']}
Commit: {failure_context['commit_message']}

IMPORTANT: When using tools, always pass these parameters explicitly:
- For GitLab tools: project_id="{webhook_data['project']['id']}"
- For session tools: session_id="{session_id}"
- For analysis tools: pipeline_id="{failure_context['pipeline_id']}", project_id="{webhook_data['project']['id']}"

Please:
1. First check session context using get_session_context(session_id="{session_id}")
2. Use GitLab tools to get pipeline details and logs (remember to pass project_id)
3. Use SonarQube tools to check for quality issues (pass project_id)
4. Search for similar historical errors
5. Provide specific, actionable fixes with confidence scores
6. Format response for UI cards with action buttons
7. Store successful fixes using store_successful_fix with session_id="{session_id}"
"""
            
            response = self.agent(prompt)
            logger.info("Agent analysis completed successfully")
            logger.debug(f"Agent response: {str(response)[:500]}...")
            
            # Parse response for cards
            cards = self._extract_cards_from_response(str(response))
            logger.info(f"Extracted {len(cards)} UI cards from response")
            
            # Store assistant response with cards
            await self.session_manager.update_conversation(
                session_id,
                {
                    "role": "assistant",
                    "content": str(response),
                    "cards": cards,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
            return {
                "session_id": session_id,
                "analysis": str(response),
                "cards": cards,
                "confidence": self._extract_confidence(str(response))
            }
            
        except Exception as e:
            logger.error(f"Analysis failed: {e}", exc_info=True)
            
            error_card = {
                "type": "error",
                "title": "Analysis Failed",
                "content": f"Failed to analyze pipeline: {str(e)}",
                "actions": [{"label": "Retry", "action": "retry_analysis"}]
            }
            
            # Store error in conversation
            await self.session_manager.update_conversation(
                session_id,
                {
                    "role": "assistant",
                    "content": f"Failed to analyze pipeline: {str(e)}",
                    "cards": [error_card],
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
            return {
                "session_id": session_id,
                "error": str(e),
                "cards": [error_card]
            }
    
    async def continue_conversation(
        self,
        session_id: str,
        user_message: str
    ) -> Dict[str, Any]:
        """Continue an existing conversation"""
        
        # Get session context
        session = await self.session_manager.get_session(session_id)
        if not session:
            raise ValueError("Session not found")
        
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
        self.agent.session_state = {
            "session_id": session_id,
            "project_id": str(session["project_id"]),
            "pipeline_id": str(session["pipeline_id"])
        }
        
        # Check if user is asking redundant questions about the fix
        lower_message = user_message.lower()
        redundant_patterns = [
            "what was the fix",
            "analyse the fix",
            "analyze the fix",
            "show me the fix",
            "explain the fix"
        ]
        
        is_redundant = any(pattern in lower_message for pattern in redundant_patterns)
        conversation_history = session.get("conversation_history", [])
        has_solution = any(
            msg.get("cards", [{}])[0].get("type") == "solution" 
            for msg in conversation_history 
            if msg.get("role") == "assistant" and msg.get("cards")
        )
        
        # If redundant question and solution already provided, give concise response
        if is_redundant and has_solution:
            response_text = "The fix has already been provided above. Would you like me to create a merge request with these changes?"
            cards = [{
                "type": "solution",
                "title": "Ready to Apply Fix",
                "confidence": 95,
                "content": "The Maven build stage solution is ready to implement.",
                "actions": [
                    {"label": "Create MR", "action": "create_mr", "data": {}},
                    {"label": "View Previous Solution", "action": "scroll_up"}
                ]
            }]
        else:
            # Run agent normally
            response = self.agent(
                f"""Continue the conversation for session {session_id}.
                
User message: {user_message}

Context:
- Session ID: {session_id}
- Project ID: {session["project_id"]}  
- Pipeline ID: {session["pipeline_id"]}

Remember to:
- Generate ONLY ONE card per response
- Avoid creating duplicate analysis cards
- Be concise if the user is asking about already-provided solutions
- Always pass IDs explicitly to tools

Previous conversation context is available via get_session_context(session_id="{session_id}").
"""
            )
            
            response_text = str(response)
            cards = self._extract_cards_from_response(response_text)
        
        # Update session with assistant response
        await self.session_manager.update_conversation(
            session_id,
            {
                "role": "assistant",
                "content": response_text,
                "cards": cards,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
        return {
            "session_id": session_id,
            "response": response_text,
            "cards": cards
        }
    
    def _extract_failed_stage(self, webhook_data: Dict[str, Any]) -> str:
        """Extract the failed stage from webhook data"""
        builds = webhook_data.get("builds", [])
        for build in builds:
            if build.get("status") == "failed":
                return build.get("stage", "unknown")
        return "unknown"
    
    def _extract_cards_from_response(self, content: str) -> List[Dict[str, Any]]:
        """Extract UI cards from agent response"""
        cards = []
        
        # Look for JSON card blocks in the response
        card_pattern = r'```json:card\s*(.*?)\s*```'
        matches = re.findall(card_pattern, content, re.DOTALL)
        
        for match in matches:
            try:
                card = json.loads(match)
                # If card has confidence field, ensure it's set at root level
                if "confidence" not in card and "confidence" in str(card.get("content", "")):
                    confidence = self._extract_confidence(str(card.get("content", "")))
                    if confidence > 0:
                        card["confidence"] = int(confidence * 100)
                cards.append(card)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse card JSON: {match}")
        
        # If no cards found, create a default one
        if not cards:
            cards.append({
                "type": "analysis",
                "title": "Pipeline Analysis",
                "content": content,
                "actions": [],
                "confidence": int(self._extract_confidence(content) * 100)
            })
        
        return cards
    
    def _extract_confidence(self, response: str) -> float:
        """Extract confidence score from response"""
        confidence_pattern = r'confidence[:\s]+(\d+)%'
        match = re.search(confidence_pattern, response, re.IGNORECASE)
        
        if match:
            return float(match.group(1)) / 100.0
        return 0.7
    
    def _extract_failed_job_name(self, webhook_data: Dict[str, Any]) -> str:
        """Extract the failed job name from webhook data"""
        builds = webhook_data.get("builds", [])
        for build in builds:
            if build.get("status") == "failed":
                return build.get("name", "unknown")
        return "unknown"