"""SonarQube quality analysis agent"""

from strands import Agent, tool
from typing import Dict, Any, List
import json
from utils.logger import log
from .base_agent import BaseAnalysisAgent
from .prompts import get_quality_system_prompt
from agents.tool_registry import tool_registry
from utils.context_extractor import ContextExtractor
from tools.sonarqube import (
    get_project_quality_gate_status,
    get_project_issues,
    get_project_metrics,
    get_issue_details,
    get_rule_description
)
from tools.gitlab import (
    get_file_content,
    create_merge_request,
    get_project_info
)


class QualityAgent(BaseAnalysisAgent):
    def __init__(self):
        super().__init__("Quality")
    
    def get_system_prompt(self) -> str:
        """Return the system prompt for quality analysis with dynamic capabilities"""
        capabilities = self.get_capabilities_description()
        return get_quality_system_prompt(capabilities)
    
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
            
            # Create enhanced prompt with context and tools
            prompt = f"""Analyze this SonarQube quality gate failure:

Project: {gitlab_project_id} 
SonarQube Project Key: {sonar_project_key}
Quality Gate Status: {webhook_data.get('qualityGate', {}).get('status', 'ERROR')}

Quality Gate Conditions that failed:
{webhook_data.get('qualityGate', {}).get('conditions', [])}

Use the available tools to:
1. Get current project metrics from SonarQube using project key: {sonar_project_key}
2. Get all project issues to understand what needs to be fixed
3. If you can access the files, retrieve the problematic code files
4. Provide specific fixes for the quality issues found

Focus on the most critical issues first: security vulnerabilities, bugs, and critical code smells.
"""

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
            
            # Create agent with enhanced context
            agent = Agent(
                model=self.model,
                system_prompt=get_quality_system_prompt(),
                tools=all_tool_objects
            )
            
            # Create wrapped get_file_content that stores files immediately - WORKING PATTERN
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
            
            return result_text
            
        except Exception as e:
            log.error(f"Error in quality analysis: {e}", exc_info=True)
            return f"Analysis failed: {str(e)}"
    
    async def handle_user_message(
        self, 
        session_id: str, 
        message: str, 
        project_id: str, 
        conversation_history: List[Dict[str, Any]]
    ) -> str:
        """Handle user message in quality analysis context"""
        try:
            log.info(f"Processing user message for quality session {session_id}")
            
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
                context_tool = ContextExtractor.create_context_tool(session_id, webhook_data, "quality")
            
            # Create tools list with conditional context tool
            tools = [
                get_project_quality_gate_status,
                get_project_issues,
                get_project_metrics,
                get_issue_details,
                get_rule_description,
                tracked_get_file_content,
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
            continuation_prompt = get_conversation_continuation_prompt("quality", context)
            
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
            return """## 🔍 Quality Gate Analysis

A SonarQube quality gate has failed and requires comprehensive analysis. To get started:

1. **First, get the failure context** using the `get_failure_context` tool to understand:
   - Project details and SonarQube configuration
   - Quality gate status and failed conditions
   - Pipeline information if this came from a pipeline failure
   - Specific metrics that are failing

2. **Then proceed with detailed analysis**:
   - Retrieve detailed issues from SonarQube using the project key
   - Examine the most critical bugs, vulnerabilities, and code smells
   - Analyze affected files and understand the quality problems
   - Prioritize fixes based on severity and impact
   - Provide comprehensive solutions to improve code quality

Start by calling `get_failure_context()` to get all the essential information you need for the analysis."""
        
        return "Please analyze the quality gate failure using the available tools."
    
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
                
                # Create comprehensive analysis prompt with the data we have
                prompt = f"""Analyze this SonarQube quality gate failure with the following comprehensive data:

**Project Information:**
- SonarQube Project Key: {project_key}
- GitLab Project ID: {gitlab_project_id}
- Quality Gate Status: {quality_gate.get('status', 'ERROR')}

**Quality Issues Summary:**
- Total Issues: {total_issues}
- Bugs: {len(bugs)}
- Vulnerabilities: {len(vulnerabilities)}
- Code Smells: {len(code_smells)}
- Critical Issues: {sonarqube_data.get("critical_issues", 0)}
- Major Issues: {sonarqube_data.get("major_issues", 0)}

**Failed Quality Gate Conditions:**
{quality_gate.get('conditions', [])}

**Detailed Issues Available:**
You have access to the complete list of issues from SonarQube. Use this information to:

1. Provide a comprehensive quality analysis
2. Prioritize the most critical issues (bugs and vulnerabilities first)
3. Explain the specific quality problems and their impact
4. Suggest concrete remediation steps
5. If you need specific file content to propose fixes, use get_file_content with the GitLab project ID

**Analysis Instructions:**
- Focus on the most severe issues first (Critical and High severity)
- Provide specific code locations and fixes where possible
- Explain the business impact of each type of issue
- Give actionable recommendations for remediation

Please provide a detailed quality analysis following the standard quality analysis format."""
            
            else:
                # Fallback to basic analysis with available webhook data
                prompt = f"""Analyze this SonarQube quality gate failure:

SonarQube Project Key: {project_key}
GitLab Project ID: {gitlab_project_id}
Quality Gate Status: {webhook_data.get('qualityGate', {}).get('status', 'ERROR')}
Failed Conditions: {webhook_data.get('qualityGate', {}).get('conditions', [])}

Analysis approach:
1. Get project metrics
2. Get all project issues - they contain file paths in the 'component' field
3. Extract file paths from the issues and retrieve those specific files
4. File paths in SonarQube format: "project_key:path/to/file.ext"
5. Extract the path after the colon for file retrieval
6. Only create MR if you successfully retrieved files with issues"""
            
            # Get tools for analysis (GitLab tools for file access)
            base_tools = self.get_agent_tools(session_id, None, webhook_data)
            
            # Add SonarQube tools if we need to fetch additional data
            if not sonarqube_data:
                sonarqube_tools = self.tool_registry.get_tools_for_agent("quality", ["sonarqube"])
                base_tools.extend(sonarqube_tools)
            
            # Create agent with tools
            agent = Agent(
                model=self.model,
                system_prompt=self.get_system_prompt(),
                tools=base_tools
            )
            
            result = await agent.invoke_async(prompt)
            log.info(f"Quality analysis complete for session {session_id}")
            
            # Extract text from result
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
            
            return result_text
            
        except Exception as e:
            log.error(f"Error in quality analysis: {e}", exc_info=True)
            return f"Analysis failed: {str(e)}"


# Backward compatibility alias
QualityAnalysisAgent = QualityAgent
