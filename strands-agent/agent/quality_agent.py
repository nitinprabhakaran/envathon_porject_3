from typing import Dict, Any, List
from datetime import datetime
import json
from loguru import logger

from strands import Agent
from strands.models import BedrockModel
from strands.models.anthropic import AnthropicModel
import os

from db.session_manager import SessionManager
from tools.sonarqube_tools import (
    get_project_quality_status,
    get_code_quality_issues,
    get_security_vulnerabilities
)
from tools.quality_tools import (
    analyze_quality_gate,
    categorize_issues,
    suggest_batch_fixes,
    create_quality_mr,
    get_all_project_issues,
    get_issue_details,
    get_issues_with_context,
    create_quality_batch_mr
)
from tools.gitlab_tools import get_file_content

QUALITY_SYSTEM_PROMPT = """You are an expert code quality analyst.

## Optimized Workflow
1. Call get_issues_with_context ONCE to get all issues
2. Group issues by file
3. Call get_file_content ONCE per file
4. Generate ALL fixes in memory
5. Call create_quality_batch_mr ONCE with all changes

## Rules
- Minimize tool calls for speed
- Fix issues based on their descriptions
- Maintain code functionality
- Create descriptive commit messages

Generate quality summary card first, then proceed with fixes."""

class QualityAnalysisAgent:
    def __init__(self):
        self.session_manager = SessionManager()
        
        # Configure model
        provider = os.getenv("LLM_PROVIDER", "bedrock").lower()
        
        if provider == "bedrock":
            model = BedrockModel(
                model_id=os.getenv("MODEL_ID", "us.anthropic.claude-3-5-sonnet-20241022-v2:0"),
                region=os.getenv("AWS_REGION", "us-west-2"),
                temperature=0.3,
                max_tokens=2048
            )
        else:
            model = AnthropicModel(
                model_id=os.getenv("MODEL_ID", "claude-3-5-sonnet-20241022"),
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                temperature=0.3,
                max_tokens=2048
            )
        
        # Initialize agent with quality tools
        self.agent = Agent(
            model=model,
            system_prompt=QUALITY_SYSTEM_PROMPT,
            tools=[
                get_project_quality_status,
                get_all_project_issues,
                get_issue_details,
                analyze_quality_gate,
                categorize_issues,
                suggest_batch_fixes,
                create_quality_mr
            ]
        )
    
    async def analyze_quality_issues(
        self,
        session_id: str,
        webhook_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze quality gate failure"""
        logger.info(f"Starting quality analysis for session {session_id}")
        
        # Extract project info
        project = webhook_data.get("project", {})
        project_key = project.get("key", "")
        quality_gate = webhook_data.get("qualityGate", {})
        
        # Set agent context
        self.agent.session_state = {
            "session_id": session_id,
            "project_key": project_key,
            "session_type": "quality"
        }
        
        prompt = f"""Analyze quality gate failure for project {project_key}:

Quality Gate: {quality_gate.get('name')}
Status: {quality_gate.get('status')}
Failed Conditions: {len([c for c in quality_gate.get('conditions', []) if c.get('status') == 'ERROR'])}

Steps:
1. Use get_all_project_issues to retrieve all issues
2. Use categorize_issues to group by type
3. Use suggest_batch_fixes for common patterns
4. Generate quality dashboard card
5. Generate issue category cards
6. Suggest batch fix options"""

        response_text = ""
        async for event in self.agent.stream_async(prompt):
            if "data" in event:
                response_text += event["data"]
        
        # Extract cards
        cards = self._extract_cards(response_text)
        
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
            "cards": cards
        }
    
    async def continue_conversation(
        self,
        session_id: str,
        user_message: str
    ) -> Dict[str, Any]:
        """Continue quality conversation"""
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
            "project_key": session.get("project_id"),
            "session_type": "quality"
        }
        
        response_text = ""
        async for event in self.agent.stream_async(user_message):
            if "data" in event:
                response_text += event["data"]
        
        cards = self._extract_cards(response_text)
        
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
    
    def _extract_cards(self, content: str) -> List[Dict[str, Any]]:
        """Extract JSON cards from response"""
        import re
        cards = []
        
        card_pattern = r'```json:card\s*(.*?)\s*```'
        matches = re.findall(card_pattern, content, re.DOTALL)
        
        for match in matches:
            try:
                card = json.loads(match)
                cards.append(card)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse card JSON: {match[:50]}...")
        
        return cards