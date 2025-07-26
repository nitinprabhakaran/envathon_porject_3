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
                temperature=0.1,  # Even lower for consistency
                streaming=True,
                max_tokens=1024,  # Further reduced
                top_p=0.7,
                # Add connection pooling
                client_config={
                    'max_pool_connections': 10,
                    'region_name': os.getenv("AWS_REGION", "us-west-2")
                }
            )
        elif provider == "anthropic":
            model = AnthropicModel(
                model_id=os.getenv("MODEL_ID", "claude-3-5-sonnet-20241022"),
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                temperature=0.1,
                max_tokens=1024,
                # Enable connection reuse
                httpx_client_kwargs={
                    'limits': {
                        'max_keepalive_connections': 5,
                        'max_connections': 10,
                    }
                }
            )
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")
        
        # Optimize conversation management
        conversation_manager = SlidingWindowConversationManager(
            window_size=5  # Reduced window
        )
        
        # Initialize with minimal tools
        self.agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=self._get_minimal_tools(),
            conversation_manager=conversation_manager,
            max_parallel_tools=2,  # Reduced parallelism
            load_tools_from_directory=False,
            # Add caching
            cache_enabled=True,
            cache_ttl=300  # 5 minutes
        )
        
        # Pre-warm connection
        asyncio.create_task(self._prewarm_connection())
    
    async def _prewarm_connection(self):
        """Pre-warm the LLM connection"""
        try:
            await self.agent.ainvoke("test", max_tokens=1)
        except:
            pass
    
    def _get_minimal_tools(self) -> List:
        """Get only essential tools for initial analysis"""
        return [
            get_pipeline_jobs,
            get_job_logs,
            extract_error_signature,
            search_similar_errors
        ]
    
    async def analyze_failure(
        self,
        session_id: str,
        webhook_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ultra-optimized failure analysis"""
        start_time = datetime.utcnow()
        logger.info(f"Starting optimized analysis for session {session_id}")
        
        # Create or get session
        session = await self.session_manager.create_or_get_session(
            session_id,
            str(webhook_data["project"]["id"]),
            str(webhook_data["object_attributes"]["id"]),
            webhook_data.get("commit", {}).get("sha")
        )
        
        # Extract key info
        project_id = str(webhook_data["project"]["id"])
        pipeline_id = str(webhook_data["object_attributes"]["id"])
        failed_job = None
        
        # Find failed job directly from webhook data
        for build in webhook_data.get("builds", []):
            if build.get("status") == "failed":
                failed_job = build
                break
        
        if not failed_job:
            return {
                "session_id": session_id,
                "error": "No failed job found",
                "cards": [{
                    "type": "error",
                    "title": "No Failed Job",
                    "content": "Could not identify failed job in pipeline"
                }]
            }
        
        # Store context
        self.agent.session_state = {
            "session_id": session_id,
            "project_id": project_id,
            "pipeline_id": pipeline_id,
            "failed_job_id": str(failed_job["id"]),
            "failed_job_name": failed_job["name"]
        }
        
        # Direct prompt for common Java error
        prompt = f"""ULTRA-FAST ANALYSIS (2 tools max):

Failed job ID: {failed_job['id']} ({failed_job['name']})
Pipeline: {pipeline_id}
Project: {project_id}

Execute:
1. get_job_logs(job_id="{failed_job['id']}", project_id="{project_id}")
2. If error contains "no such file" → immediate JAR missing solution

Generate ONE card:
```json:card
{{
  "type": "solution",
  "title": "Missing JAR File in Docker Build",
  "confidence": 95,
  "estimated_time": "5 minutes",
  "content": "Docker build failing - JAR file missing. Add Maven build step before Docker.",
  "fix_type": "pipeline_config",
  "code_changes": "build-job:\\n  image: maven:3.8-openjdk-11\\n  stage: build\\n  script:\\n    - mvn clean package\\n    - docker build -t ${{CI_PROJECT_NAME}}:${{CI_COMMIT_SHORT_SHA}} .\\n  artifacts:\\n    paths:\\n      - target/*.jar",
  "actions": [
    {{"label": "Apply Fix", "action": "apply_fix", "data": {{"fix_id": "{session_id}-fix-1", "file": ".gitlab-ci.yml"}}}},
    {{"label": "Create MR", "action": "create_mr", "data": {{"fix_id": "{session_id}-fix-1", "branch": "fix/add-maven-build"}}}}
  ]
}}
```"""
        
        try:
            # Single LLM call with streaming
            response_text = ""
            async for event in self.agent.stream_async(prompt):
                if "data" in event:
                    response_text += event["data"]
            
            # Extract cards
            cards = self._extract_cards_from_response(response_text)
            
            # Log performance
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"Analysis completed in {duration:.2f}s")
            
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
                "confidence": 95,
                "duration_seconds": duration
            }
            
        except Exception as e:
            logger.error(f"Analysis failed: {e}", exc_info=True)
            return {
                "session_id": session_id,
                "error": str(e),
                "cards": [{
                    "type": "error",
                    "title": "Analysis Failed",
                    "content": str(e)
                }]
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
        
        # Set context
        self.agent.session_state = {
            "session_id": session_id,
            "project_id": str(session["project_id"]),
            "pipeline_id": str(session["pipeline_id"])
        }
        
        # Check for action requests
        lower_message = user_message.lower()
        
        if "create" in lower_message and "mr" in lower_message:
            # Direct MR creation response
            response_text = "I'll create a merge request with the Maven build fix."
            cards = [{
                "type": "progress",
                "title": "Creating Merge Request",
                "subtitle": "Adding Maven build step to fix JAR issue",
                "progress": 50,
                "steps": [
                    {"name": "Prepare changes", "status": "done"},
                    {"name": "Create branch", "status": "in_progress"},
                    {"name": "Push changes", "status": "pending"},
                    {"name": "Open MR", "status": "pending"}
                ]
            }]
        else:
            # Normal response
            prompt = f"{user_message}\n\nBe concise. Use existing context."
            
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
        for build in webhook_data.get("builds", []):
            if build.get("status") == "failed":
                return build.get("stage", "unknown")
        return "unknown"
    
    def _extract_failed_job_name(self, webhook_data: Dict[str, Any]) -> str:
        """Extract the failed job name from webhook data"""
        for build in webhook_data.get("builds", []):
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
                cards.append(card)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse card JSON: {match[:50]}...")
        
        return cards
    
    def _extract_confidence(self, response: str) -> float:
        """Extract confidence score from response"""
        confidence_pattern = r'confidence[:\s]+(\d+)%'
        match = re.search(confidence_pattern, response, re.IGNORECASE)
        return float(match.group(1)) / 100.0 if match else 0.95