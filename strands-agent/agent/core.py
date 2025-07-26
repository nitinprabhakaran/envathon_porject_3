from typing import Dict, List, Any, Optional
from datetime import datetime
import json
import re
import os
from loguru import logger

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
                temperature=0.3,  # Lower temperature for more consistent results
                streaming=True,   # Enable streaming for better UX
                max_tokens=2048,  # Reduced for faster responses
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
            window_size=10  # Limit context size
        )
        
        # Initialize with minimal tools for initial analysis
        self.agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=self._get_minimal_tools(),
            conversation_manager=conversation_manager,
            load_tools_from_directory=False  # Explicit control
        )
    
    def _get_minimal_tools(self) -> List:
        """Get only essential tools for initial analysis"""
        return [
            # Core analysis tools only
            get_pipeline_jobs,
            get_job_logs,
            analyze_pipeline_logs,
            extract_error_signature,
            search_similar_errors,
            get_session_context
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
            create_merge_request,
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
        prompt = f"""QUICK ANALYSIS - Use only essential tools:

Pipeline #{failure_context['pipeline_id']} failed in {failure_context['failed_stage']} stage
Job: {failure_context['job_name']}
Project: {failure_context['project_name']} (ID: {webhook_data['project']['id']})

EXECUTE IN ORDER (3-4 tools max):
1. get_pipeline_jobs(pipeline_id="{failure_context['pipeline_id']}", project_id="{webhook_data['project']['id']}")
2. get_job_logs(job_id="<failed_job_id>", project_id="{webhook_data['project']['id']}")
3. search_similar_errors(error_signature="<extracted_signature>")

Generate ONE solution card with:
- Root cause
- Specific fix (95% confidence for missing JAR errors)
- Code changes
- Action buttons: "Apply Fix", "Create MR"

Skip: quality checks, file content, comments, storing fixes"""
        
        try:
            # Use streaming for better UX
            response_text = ""
            async for event in self.agent.stream_async(prompt):
                if "data" in event:
                    response_text += event["data"]
            
            # Extract cards
            cards = self._extract_cards_from_response(response_text)
            
            # Log performance
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"Analysis completed in {duration:.2f}s with {len(cards)} cards")
            
            # Store response
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
                "analysis": response_text,
                "cards": cards,
                "confidence": self._extract_confidence(response_text),
                "duration_seconds": duration
            }
            
        except Exception as e:
            logger.error(f"Analysis failed: {e}", exc_info=True)
            error_card = {
                "type": "error",
                "title": "Analysis Failed",
                "content": str(e),
                "actions": [{"label": "Retry", "action": "retry_analysis"}]
            }
            
            await self.session_manager.update_conversation(
                session_id,
                {
                    "role": "assistant",
                    "content": f"Error: {str(e)}",
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
        """Optimized conversation continuation"""
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
            "pipeline_id": str(session["pipeline_id"])
        }
        
        # Check for redundant questions
        lower_message = user_message.lower()
        redundant_patterns = ["what was the fix", "analyse the fix", "show me the fix"]
        
        if any(pattern in lower_message for pattern in redundant_patterns):
            # Check if solution already provided
            conv_history = session.get("conversation_history", [])
            has_solution = any(
                msg.get("cards", [{}])[0].get("type") == "solution" 
                for msg in conv_history 
                if msg.get("role") == "assistant" and msg.get("cards")
            )
            
            if has_solution:
                response_text = "The fix is already provided above. Ready to create a merge request?"
                cards = [{
                    "type": "solution",
                    "title": "Ready to Apply",
                    "confidence": 95,
                    "content": "Maven build stage solution is ready.",
                    "actions": [
                        {"label": "Create MR", "action": "create_mr", "data": {}},
                        {"label": "View Fix Above", "action": "scroll_up"}
                    ]
                }]
                
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
        
        # Generate response
        prompt = f"{user_message}\n\nContext: Session {session_id}, Project {session['project_id']}\nUse minimal tools."
        
        response_text = ""
        async for event in self.agent.stream_async(prompt):
            if "data" in event:
                response_text += event["data"]
        
        cards = self._extract_cards_from_response(response_text)
        
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
    
    def _extract_failed_job_name(self, webhook_data: Dict[str, Any]) -> str:
        """Extract the failed job name from webhook data"""
        builds = webhook_data.get("builds", [])
        for build in builds:
            if build.get("status") == "failed":
                return build.get("name", "unknown")
        return "unknown"
    
    def _extract_cards_from_response(self, content: str) -> List[Dict[str, Any]]:
        """Extract UI cards from agent response"""
        cards = []
        
        # Look for JSON card blocks
        card_pattern = r'```json:card\s*(.*?)\s*```'
        matches = re.findall(card_pattern, content, re.DOTALL)
        
        for match in matches:
            try:
                card = json.loads(match)
                # Ensure confidence is set
                if "confidence" not in card and card.get("type") == "solution":
                    card["confidence"] = 95  # Default high confidence for clear errors
                cards.append(card)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse card JSON: {match[:50]}...")
        
        # Create default if no cards
        if not cards:
            cards.append({
                "type": "analysis",
                "title": "Pipeline Analysis",
                "content": content,
                "confidence": 70,
                "actions": []
            })
        
        return cards
    
    def _extract_confidence(self, response: str) -> float:
        """Extract confidence score from response"""
        confidence_pattern = r'confidence[:\s]+(\d+)%'
        match = re.search(confidence_pattern, response, re.IGNORECASE)
        return float(match.group(1)) / 100.0 if match else 0.7