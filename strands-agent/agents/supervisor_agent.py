"""
Supervisor Agent for AWS Strands Agent Communication
Implements the SupervisorAgent pattern from AWS Agent Squad framework
"""

import logging
from typing import Dict, Any, Optional, List
from strands import tool, Agent
from .base_agent import BaseAnalysisAgent

logger = logging.getLogger(__name__)

class SupervisorAgent(BaseAnalysisAgent):
    """
    Supervisor Agent that coordinates between Pipeline and Quality agents
    Following AWS Agent Squad SupervisorAgent pattern
    """
    
    def __init__(self):
        try:
            super().__init__("supervisor")
            logger.info("Supervisor agent initialized successfully")
        except Exception as e:
            logger.error(f"Supervisor agent initialization failed: {e}")
            # Continue initialization but mark model as unavailable
            self.agent_type = "supervisor"
            self.model = None
            
            # Initialize session manager separately
            try:
                from db.session_manager import SessionManager
                self._session_manager = SessionManager()
            except Exception as sm_error:
                logger.error(f"Session manager initialization failed: {sm_error}")
                self._session_manager = None
                
            logger.warning("Supervisor agent running in fallback mode (no model)")
    
    def _check_aws_credentials(self) -> bool:
        """Check if AWS credentials are properly configured"""
        try:
            import boto3
            from config import settings
            
            # Try to create a client and make a basic call
            client = boto3.client(
                'bedrock-runtime',
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                aws_session_token=settings.aws_session_token
            )
            
            # This will fail quickly if credentials are invalid
            client.get_caller_identity = lambda: {"Account": "test"}
            return True
            
        except Exception as e:
            logger.warning(f"AWS credentials check failed: {e}")
            return False
    
    def create_specialized_agent_tools(self, session_id: str, project_id: str, webhook_data: Dict[str, Any]):
        """Create tools for delegating to specialized agents"""
        
        @tool
        async def analyze_with_pipeline_agent(
            reason: str,
            context_summary: str
        ) -> str:
            """
            Delegate analysis to the Pipeline Agent specialist
            
            Args:
                reason: Why this should be handled by the pipeline agent
                context_summary: Brief summary of the failure context
            """
            try:
                logger.info(f"Supervisor delegating to Pipeline Agent: {reason}")
                
                # Import pipeline agent dynamically to avoid circular imports
                from .pipeline_agent import pipeline_agent
                
                # Use the global pipeline agent instance
                result = await pipeline_agent.analyze_failure(
                    session_id, project_id, webhook_data.get("object_attributes", {}).get("id", ""), webhook_data
                )
                
                return f"**Pipeline Analysis Completed**\n\n{result}"
                
            except Exception as e:
                logger.error(f"Error delegating to pipeline agent: {e}")
                return f"❌ Pipeline analysis failed: {str(e)}"
        
        @tool
        async def analyze_with_quality_agent(
            reason: str,
            context_summary: str,
            sonarqube_project_key: str
        ) -> str:
            """
            Delegate analysis to the Quality Agent specialist
            
            Args:
                reason: Why this should be handled by the quality agent  
                context_summary: Brief summary of the failure context
                sonarqube_project_key: The SonarQube project key for analysis
            """
            try:
                logger.info(f"Supervisor delegating to Quality Agent: {reason}")
                
                # Import quality agent dynamically to avoid circular imports
                from .quality_agent import quality_agent
                
                # Map SonarQube project key to GitLab project ID
                from api.webhooks import get_gitlab_project_id
                gitlab_project_id = await get_gitlab_project_id(sonarqube_project_key)
                if not gitlab_project_id:
                    gitlab_project_id = project_id
                
                # Pre-fetch SonarQube data and store metrics before analysis (like the queue processor does)
                try:
                    from tools.sonarqube import get_project_issues, get_project_metrics, get_project_quality_gate_status
                    from db.session_manager import SessionManager
                    
                    # Get SonarQube data
                    quality_status = await get_project_quality_gate_status(sonarqube_project_key)
                    project_status = quality_status.get("projectStatus", {})
                    
                    if project_status.get("status") != "NONE" and project_status:
                        # Get issue counts by type
                        bugs = await get_project_issues(sonarqube_project_key, types="BUG", limit=500)
                        vulnerabilities = await get_project_issues(sonarqube_project_key, types="VULNERABILITY", limit=500) 
                        code_smells = await get_project_issues(sonarqube_project_key, types="CODE_SMELL", limit=500)
                        
                        # Get project metrics
                        try:
                            metrics = await get_project_metrics(sonarqube_project_key)
                        except Exception as e:
                            logger.warning(f"Could not fetch metrics for {sonarqube_project_key}: {e}")
                            metrics = {}
                        
                        # Calculate counts
                        total_issues = len(bugs) + len(vulnerabilities) + len(code_smells)
                        critical_count = sum(1 for b in bugs if b.get("severity") in ["CRITICAL", "BLOCKER"])
                        critical_count += sum(1 for v in vulnerabilities if v.get("severity") in ["CRITICAL", "BLOCKER"])
                        major_count = sum(1 for b in bugs if b.get("severity") == "MAJOR")
                        major_count += sum(1 for v in vulnerabilities if v.get("severity") == "MAJOR")
                        
                        # Store quality metrics in database BEFORE running agent analysis
                        session_manager = SessionManager()
                        metrics_to_update = {
                            "total_issues": total_issues,
                            "bug_count": len(bugs),
                            "vulnerability_count": len(vulnerabilities),
                            "code_smell_count": len(code_smells),
                            "critical_issues": critical_count,
                            "major_issues": major_count,
                            "coverage": metrics.get("coverage", "0"),
                            "duplicated_lines_density": metrics.get("duplicated_lines_density", "0"),
                            "reliability_rating": metrics.get("reliability_rating", "E"),
                            "security_rating": metrics.get("security_rating", "E"),
                            "maintainability_rating": metrics.get("maintainability_rating", "E")
                        }
                        
                        logger.info(f"Storing quality metrics for session {session_id}: {metrics_to_update}")
                        await session_manager.update_quality_metrics(session_id, metrics_to_update)
                        
                        # Enhanced webhook data for agent
                        enhanced_webhook_data = {
                            **webhook_data,
                            "qualityGate": project_status,
                            "sonarqube_data": {
                                "bugs": bugs,
                                "vulnerabilities": vulnerabilities,
                                "code_smells": code_smells,
                                "metrics": metrics,
                                "total_issues": total_issues,
                                "critical_issues": critical_count,
                                "major_issues": major_count
                            }
                        }
                        
                        # Use enhanced webhook data for quality agent
                        result = await quality_agent.analyze_quality_issues(
                            session_id, sonarqube_project_key, gitlab_project_id, enhanced_webhook_data
                        )
                    else:
                        # No quality gate configured - use original webhook data
                        result = await quality_agent.analyze_quality_issues(
                            session_id, sonarqube_project_key, gitlab_project_id, webhook_data
                        )
                        
                except Exception as metrics_error:
                    logger.error(f"Failed to pre-fetch quality metrics: {metrics_error}")
                    # Fall back to original analysis without enhanced metrics
                    result = await quality_agent.analyze_quality_issues(
                        session_id, sonarqube_project_key, gitlab_project_id, webhook_data
                    )
                
                return f"**Quality Analysis Completed**\n\n{result}"
                
            except Exception as e:
                logger.error(f"Error delegating to quality agent: {e}")
                return f"❌ Quality analysis failed: {str(e)}"
        
        @tool
        async def check_session_continuity() -> str:
            """
            Check if this failure should continue an existing session
            Returns information about session continuity
            """
            try:
                from services.session_continuity import SessionContinuityManager
                from db.session_manager import SessionManager
                
                session_manager = SessionManager()
                continuity_manager = SessionContinuityManager(session_manager)
                
                should_continue, existing_session_id = await continuity_manager.should_continue_session(
                    project_id, webhook_data, None
                )
                
                if should_continue and existing_session_id:
                    return f"🔄 **Session Continuity Detected**: This failure should continue existing session {existing_session_id} instead of creating a new session."
                else:
                    return "✅ **New Session**: This is a new failure requiring a fresh analysis session."
                    
            except Exception as e:
                logger.error(f"Error checking session continuity: {e}")
                return f"⚠️ Session continuity check failed: {str(e)}"
        
        return [analyze_with_pipeline_agent, analyze_with_quality_agent, check_session_continuity]
    
    async def coordinate_failure_analysis(
        self,
        session_id: str,
        project_id: str,
        webhook_data: Dict[str, Any],
        failure_context: Dict[str, Any] = None
    ) -> str:
        """
        Coordinate failure analysis by delegating to appropriate specialist
        
        Args:
            session_id: The session ID for this analysis
            project_id: GitLab project ID
            webhook_data: Webhook payload data
            failure_context: Additional context about the failure
        
        Returns:
            Analysis result from the delegated specialist agent
        """
        try:
            logger.info(f"Supervisor coordinating failure analysis for session {session_id}")
            
            # Check if model is available
            if not self.model:
                logger.warning("Model not available, using rule-based fallback")
                return await self._fallback_rule_based_delegation(
                    session_id, project_id, webhook_data, failure_context, "Model not initialized"
                )
            
            # Create specialized agent tools
            tools = self.create_specialized_agent_tools(session_id, project_id, webhook_data)
            
            # Build context for analysis
            pipeline_info = webhook_data.get("object_attributes", {})
            project_info = webhook_data.get("project", {})
            
            # Extract key failure indicators
            pipeline_status = pipeline_info.get("status", "unknown")
            pipeline_stage = pipeline_info.get("stage", "unknown") 
            pipeline_url = pipeline_info.get("web_url", "")
            project_name = project_info.get("name", project_id)
            
            # Build the analysis prompt
            analysis_prompt = f"""
## Failure Analysis Request

**Project**: {project_name} (ID: {project_id})
**Pipeline**: {pipeline_info.get('id', 'unknown')} 
**Status**: {pipeline_status}
**Stage**: {pipeline_stage}
**URL**: {pipeline_url}

### Context Data:
```json
{webhook_data}
```

### Additional Context:
{failure_context or "No additional context provided"}

Please analyze this failure and delegate to the appropriate specialized agent. 

1. First, check if this should continue an existing session
2. Analyze the failure type and context
3. Delegate to either the Pipeline Agent or Quality Agent
4. Provide a comprehensive analysis result

Remember to maintain session continuity if detected and include any infrastructure alerts.
"""
            
            # Try to run the analysis with proper error handling
            try:
                # Create the supervisor agent
                agent = Agent(
                    model=self.model,
                    system_prompt=self.get_system_prompt(),
                    tools=tools
                )
                
                # Run the analysis
                response = await agent.invoke_async(analysis_prompt)
                result_text = self.extract_text_from_response(response)
                
                logger.info(f"Supervisor coordination completed for session {session_id}")
                return result_text
                
            except Exception as model_error:
                logger.error(f"Model invocation failed: {model_error}")
                
                # Fallback to rule-based delegation when model fails
                logger.info("Falling back to rule-based delegation due to model error")
                return await self._fallback_rule_based_delegation(
                    session_id, project_id, webhook_data, failure_context, str(model_error)
                )
            
        except Exception as e:
            logger.error(f"Supervisor coordination failed: {e}")
            return f"❌ Supervisor coordination failed: {str(e)}"
    
    async def _fallback_rule_based_delegation(
        self,
        session_id: str,
        project_id: str,
        webhook_data: Dict[str, Any],
        failure_context: Dict[str, Any],
        model_error: str
    ) -> str:
        """
        Fallback rule-based delegation when LLM is unavailable
        Uses the original hardcoded logic as a backup
        """
        try:
            logger.info(f"Using rule-based fallback delegation for session {session_id}")
            
            # Extract failure indicators for rule-based classification
            pipeline_info = webhook_data.get("object_attributes", {})
            pipeline_stage = pipeline_info.get("stage", "").lower()
            failure_context_data = failure_context or {}
            webhook_indicators = failure_context_data.get("webhook_indicators", {})
            
            # Rule-based classification logic
            is_quality_failure = False
            
            # Check for quality indicators
            quality_detected_by_handler = webhook_indicators.get("quality_detected_by_handler", False)
            quality_in_stage = any(keyword in pipeline_stage for keyword in ["quality", "sonar", "test", "coverage"])
            
            if quality_detected_by_handler or quality_in_stage:
                is_quality_failure = True
                logger.info(f"Rule-based classification: Quality failure detected")
            else:
                logger.info(f"Rule-based classification: Pipeline failure detected")
            
            # Delegate to appropriate agent
            if is_quality_failure:
                # Import and use quality agent
                from .quality_agent import quality_agent
                
                # Extract or construct SonarQube project key
                project_info = webhook_data.get("project", {})
                namespace = project_info.get("namespace", {}).get("name", "")
                project_name = project_info.get("name", "")
                sonarqube_project_key = f"{namespace}:{project_name}" if namespace else project_name
                
                # Map to GitLab project ID
                try:
                    from api.webhooks import get_gitlab_project_id
                    gitlab_project_id = await get_gitlab_project_id(sonarqube_project_key)
                    if not gitlab_project_id:
                        gitlab_project_id = project_id
                except Exception as e:
                    logger.warning(f"Could not map SonarQube project to GitLab: {e}")
                    gitlab_project_id = project_id
                
                logger.info(f"Fallback delegating to Quality Agent: {sonarqube_project_key}")
                result = await quality_agent.analyze_quality_issues(
                    session_id, sonarqube_project_key, gitlab_project_id, webhook_data
                )
                
                delegation_note = f"🔄 **Fallback Delegation to Quality Agent**\n*(LLM unavailable: {model_error})*\n\n"
                return delegation_note + str(result)
                
            else:
                # Import and use pipeline agent
                from .pipeline_agent import pipeline_agent
                
                logger.info(f"Fallback delegating to Pipeline Agent")
                result = await pipeline_agent.analyze_failure(
                    session_id, project_id, pipeline_info.get("id", ""), webhook_data
                )
                
                delegation_note = f"🔄 **Fallback Delegation to Pipeline Agent**\n*(LLM unavailable: {model_error})*\n\n"
                return delegation_note + str(result)
                
        except Exception as e:
            logger.error(f"Fallback delegation also failed: {e}")
            return f"""❌ **Supervisor Coordination Failed**

**Primary Error**: {model_error}
**Fallback Error**: {str(e)}

**Manual Action Required**: Please check AWS credentials and model configuration, or contact system administrator.

**Session ID**: {session_id}
**Project ID**: {project_id}
"""
    
    async def analyze_failure(self, session_id: str, project_id: str, pipeline_id: str, webhook_data: Dict[str, Any]) -> str:
        """
        Analyze failure using intelligent coordination - required by BaseAnalysisAgent
        This is the main entry point for failure analysis
        """
        failure_context = {
            "event_type": "pipeline_failure",
            "pipeline_id": pipeline_id,
            "project_id": project_id
        }
        
        return await self.coordinate_failure_analysis(
            session_id, project_id, webhook_data, failure_context
        )
    
    async def handle_user_message(self, session_id: str, user_message: str, conversation_history: List[Dict[str, Any]]) -> str:
        """
        Handle user messages in supervisor context - required by BaseAnalysisAgent
        Not typically used for supervisor agents, but required by interface
        """
        return "❌ Direct user interaction is not supported by the SupervisorAgent. Please use specialized agents."
    
    def get_system_prompt(self) -> str:
        """Get the system prompt for the supervisor agent"""
        return """
You are a CI/CD Failure Analysis Supervisor Agent. Your role is to analyze incoming failure events and intelligently delegate to specialized agents.

## Available Specialized Agents:

### Pipeline Agent
- **Expertise**: Build failures, compilation errors, dependency issues, test failures, deployment problems
- **When to use**: When the failure is related to the CI/CD pipeline itself (build, test, deploy stages)
- **Indicators**: Build logs, compilation errors, test failures, deployment issues, infrastructure problems

### Quality Agent  
- **Expertise**: Code quality issues, SonarQube analysis, security vulnerabilities, code smells, coverage issues
- **When to use**: When the failure is related to quality gates, code analysis, or SonarQube reports
- **Indicators**: Quality gate failures, SonarQube reports, code coverage issues, security vulnerabilities

## Your Decision Process:

1. **Analyze the Context**: Examine the failure data, logs, and webhook information
2. **Classify the Issue**: Determine if this is primarily a pipeline issue or quality issue  
3. **Delegate Appropriately**: Use the relevant specialized agent to handle the analysis
4. **Coordinate Response**: Ensure proper session continuity and context sharing

## Important Guidelines:

- **Single Agent Delegation**: Choose ONE primary agent based on the failure type
- **Context Preservation**: Maintain session continuity and pass relevant context
- **Infrastructure Issues**: If you detect configuration problems (like missing SonarQube setup), include infrastructure alerts
- **Session Continuity**: Check if this should continue an existing session rather than creating a new one

## Tools Available:
- `analyze_with_pipeline_agent`: Delegate to pipeline specialist for build/deployment issues
- `analyze_with_quality_agent`: Delegate to quality specialist for code quality issues
- `check_session_continuity`: Check if this should continue an existing session

Analyze the failure context and delegate to the most appropriate specialist agent.
"""

# Create global supervisor agent instance
supervisor_agent = SupervisorAgent()
