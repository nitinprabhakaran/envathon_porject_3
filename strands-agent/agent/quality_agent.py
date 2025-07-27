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
    get_security_vulnerabilities,
    get_issues_with_context
)
from tools.quality_tools import (
    analyze_quality_gate,
    categorize_issues,
    suggest_batch_fixes,
    create_quality_mr,
    get_all_project_issues,
    get_issue_details,
    create_quality_batch_mr
)
from tools.gitlab_tools import get_file_content, create_merge_request

QUALITY_SYSTEM_PROMPT = """You are an expert code quality analyst.

When analyzing SonarQube quality gate failures:
- The session context contains both 'sonarqube_key' (for SonarQube API) and 'project_id' (for GitLab API)
- Use the appropriate ID for each API

Output format:
- Start with a summary of issues found
- If it is feasible, show small snippets of the changes you made in code
- Show the fixes applied
- End with the merge request status

Do not describe the tools you used or the workflow steps."""

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
                get_issues_with_context,
                get_file_content,
                create_merge_request,
                get_project_quality_status,
                analyze_quality_gate
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
        sonarqube_key = webhook_data.get("_sonarqube_key", project.get("key", ""))
        gitlab_project_id = webhook_data.get("_gitlab_project_id", "")
        quality_gate = webhook_data.get("qualityGate", {})
        
        # Set agent context with both IDs
        self.agent.session_state = {
            "session_id": session_id,
            "project_id": gitlab_project_id,  # For GitLab API calls
            "sonarqube_key": sonarqube_key,  # For SonarQube API calls
            "session_type": "quality"
        }
        
        prompt = f"""Quality gate failed for project {sonarqube_key}.

GitLab project ID: {gitlab_project_id}
SonarQube key: {sonarqube_key}

1. Use get_issues_with_context(project_key="{sonarqube_key}") to get all issues
2. For each file with issues, use get_file_content(file_path="path/to/file.py", ref="HEAD", project_id="{gitlab_project_id}")
3. Fix all issues in the files
4. Create a merge request using create_merge_request(..., project_id="{gitlab_project_id}")

Remember to use project_id="{gitlab_project_id}" for GitLab API calls."""

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
        
        return {
            "session_id": session_id,
            "analysis": response_text
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
        webhook_data = session.get("webhook_data", {})
        self.agent.session_state = {
            "session_id": session_id,
            "project_id": session.get("project_id"),
            "sonarqube_key": webhook_data.get("_sonarqube_key", ""),
            "session_type": "quality"
        }
        
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