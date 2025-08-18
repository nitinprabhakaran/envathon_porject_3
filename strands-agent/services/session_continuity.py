"""
Session Continuity Manager for AWS Strands Agent Communication
Implements proper session handoff between agents as per AWS Strands patterns
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import re

logger = logging.getLogger(__name__)

@dataclass
class AgentHandoffContext:
    """Context for passing information between agents"""
    source_agent: str
    target_agent: str
    session_id: str
    project_id: str
    pipeline_id: str
    branch: str
    previous_analysis: Dict[str, Any]
    handoff_reason: str
    infrastructure_alerts: List[str] = None
    
    def __post_init__(self):
        if self.infrastructure_alerts is None:
            self.infrastructure_alerts = []

class SessionContinuityManager:
    """
    Manages session continuity and agent handoffs following AWS Strands patterns
    """
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.logger = logger
        
    async def should_continue_session(self, project_id: str, webhook_data: Dict[str, Any], 
                                    context: Any = None) -> tuple[bool, Optional[str]]:
        """
        Check if we should continue an existing session instead of using the current one.
        Returns (should_continue, existing_session_id)
        """
        try:
            # Extract branch from webhook data
            branch = webhook_data.get("ref", "").replace("refs/heads/", "")
            pipeline_id = webhook_data.get("object_attributes", {}).get("id")
            
            existing_session_id = await self.check_session_continuity(
                project_id, branch, str(pipeline_id) if pipeline_id else None
            )
            
            if existing_session_id:
                return True, existing_session_id
            else:
                return False, None
                
        except Exception as e:
            self.logger.error(f"Error in should_continue_session: {e}")
            return False, None
        
    async def check_session_continuity(self, project_id: str, branch: str, 
                                     pipeline_id: str = None) -> Optional[str]:
        """
        Check if there's an existing session that should continue.
        This implements the AWS Strands pattern of session continuity across pipeline stages.
        """
        try:
            # First check if this is a fix branch from an existing session
            if self._is_fix_branch(branch):
                existing_session = await self._get_session_by_fix_branch(branch)
                if existing_session:
                    self.logger.info(
                        f"Found existing session {existing_session['session_id']} "
                        f"for fix branch {branch}"
                    )
                    return existing_session['session_id']
            
            # Check for active sessions on the same project within the last 2 hours
            # This catches cases where the same project has multiple pipeline failures
            active_session = await self._get_recent_active_session(project_id)
            if active_session:
                self.logger.info(
                    f"Found recent active session {active_session['session_id']} "
                    f"for project {project_id}"
                )
                return active_session['session_id']
                
            return None
            
        except Exception as e:
            self.logger.error(f"Error checking session continuity: {e}")
            return None
    
    async def detect_infrastructure_issues(self, project_id: str, sonarqube_key: str = None) -> str:
        """
        Detect infrastructure issues that might be causing failures.
        Returns a formatted string of issues found or empty string if none.
        """
        try:
            issues = []
            
            # Check SonarQube configuration if key provided
            if sonarqube_key:
                try:
                    from tools.sonarqube import get_project_quality_gate_status
                    quality_status = await get_project_quality_gate_status(sonarqube_key)
                    project_status = quality_status.get("projectStatus", {})
                    
                    if project_status.get("status") == "NONE" or not project_status:
                        issues.append(f"⚠️ **SonarQube Configuration Issue**: No analysis results found for project '{sonarqube_key}'. This may indicate missing SonarQube integration in the CI/CD pipeline.")
                        
                except Exception as e:
                    issues.append(f"⚠️ **SonarQube Connection Issue**: Unable to fetch quality gate status - {str(e)}")
            
            # Add other infrastructure checks here as needed
            # - Database connectivity
            # - External service availability  
            # - Configuration validation
            
            return "\n".join(issues) if issues else ""
            
        except Exception as e:
            self.logger.error(f"Error detecting infrastructure issues: {e}")
            return f"⚠️ **Infrastructure Check Failed**: {str(e)}"
    
    def _is_fix_branch(self, branch: str) -> bool:
        """Check if this is a fix branch created by the system"""
        fix_patterns = [
            r'^fix/pipeline_',
            r'^fix/quality_'
        ]
        
        for pattern in fix_patterns:
            if re.match(pattern, branch):
                return True
        return False
    
    async def _get_session_by_fix_branch(self, branch: str) -> Optional[Dict[str, Any]]:
        """Get session that created this fix branch"""
        try:
            query = """
                SELECT s.id as session_id, s.project_id, s.session_type, s.status
                FROM sessions s
                JOIN fix_attempts fa ON s.id = fa.session_id
                WHERE fa.branch_name = %s
                AND s.status = 'active'
                ORDER BY fa.created_at DESC
                LIMIT 1
            """
            
            async with self.db_manager.get_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(query, (branch,))
                    result = await cursor.fetchone()
                    
                    if result:
                        return {
                            'session_id': result[0],
                            'project_id': result[1],
                            'session_type': result[2],
                            'status': result[3]
                        }
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting session by fix branch: {e}")
            return None
    
    async def _get_recent_active_session(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get recent active session for the same project"""
        try:
            query = """
                SELECT id as session_id, session_type, status, pipeline_id
                FROM sessions 
                WHERE project_id = %s 
                AND status = 'active'
                AND created_at > NOW() - INTERVAL '2 hours'
                ORDER BY created_at DESC
                LIMIT 1
            """
            
            async with self.db_manager.get_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(query, (project_id,))
                    result = await cursor.fetchone()
                    
                    if result:
                        return {
                            'session_id': result[0],
                            'session_type': result[1],
                            'status': result[2],
                            'pipeline_id': result[3]
                        }
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting recent active session: {e}")
            return None
    
    async def create_agent_handoff(self, context: AgentHandoffContext) -> bool:
        """
        Create agent handoff record and update session
        """
        try:
            # Update session type and add handoff record
            await self._update_session_agent(context.session_id, context.target_agent)
            await self._record_agent_handoff(context)
            
            self.logger.info(
                f"Agent handoff completed: {context.source_agent} → {context.target_agent} "
                f"for session {context.session_id}. Reason: {context.handoff_reason}"
            )
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating agent handoff: {e}")
            return False
    
    async def _update_session_agent(self, session_id: str, new_agent_type: str):
        """Update session type for agent handoff"""
        try:
            query = """
                UPDATE sessions 
                SET session_type = %s, updated_at = NOW()
                WHERE id = %s
            """
            
            async with self.db_manager.get_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(query, (new_agent_type, session_id))
                    
        except Exception as e:
            self.logger.error(f"Error updating session agent: {e}")
            raise
    
    async def _record_agent_handoff(self, context: AgentHandoffContext):
        """Record agent handoff for audit and debugging"""
        try:
            query = """
                INSERT INTO agent_handoffs (
                    session_id, source_agent, target_agent, handoff_reason,
                    project_id, pipeline_id, branch, infrastructure_alerts,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """
            
            alerts_json = ','.join(context.infrastructure_alerts) if context.infrastructure_alerts else None
            
            async with self.db_manager.get_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(query, (
                        context.session_id,
                        context.source_agent,
                        context.target_agent,
                        context.handoff_reason,
                        context.project_id,
                        context.pipeline_id,
                        context.branch,
                        alerts_json
                    ))
                    
        except Exception as e:
            self.logger.error(f"Error recording agent handoff: {e}")
            # Don't raise - this is for audit purposes only
    
    async def get_session_context(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get full session context for agent handoff"""
        try:
            query = """
                SELECT 
                    s.id, s.session_type, s.project_id, s.pipeline_id, s.branch,
                    s.conversation_history, s.analysis_result, s.status,
                    s.commit_sha, s.merge_request_url
                FROM sessions s
                WHERE s.id = %s
            """
            
            async with self.db_manager.get_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(query, (session_id,))
                    result = await cursor.fetchone()
                    
                    if result:
                        return {
                            'session_id': result[0],
                            'session_type': result[1],
                            'project_id': result[2],
                            'pipeline_id': result[3],
                            'branch': result[4],
                            'conversation_history': result[5],
                            'analysis_result': result[6],
                            'status': result[7],
                            'commit_sha': result[8],
                            'merge_request_url': result[9]
                        }
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting session context: {e}")
            return None
    
    def create_infrastructure_alert(self, issue_type: str, details: str, 
                                  project_name: str) -> str:
        """Create infrastructure alert message"""
        
        alerts = {
            'sonarqube_not_configured': f"""
## 🚨 Infrastructure Issue: SonarQube Not Configured

**Project**: {project_name}
**Issue**: SonarQube analysis is not set up for this project

### Required Actions:
1. **Configure SonarQube Project**: Set up project in SonarQube server
2. **Update Pipeline**: Add SonarQube analysis step to `.gitlab-ci.yml`
3. **Set Environment Variables**: Configure `SONAR_HOST_URL` and `SONAR_TOKEN`

### Example Pipeline Configuration:
```yaml
sonarqube_scan:
  stage: quality
  script:
    - sonar-scanner 
      -Dsonar.projectKey={project_name}
      -Dsonar.sources=src
      -Dsonar.host.url=${{SONAR_HOST_URL}}
      -Dsonar.login=${{SONAR_TOKEN}}
  only:
    - main
    - merge_requests
```

### Contact DevOps team to resolve this infrastructure issue.
""",
            
            'quality_gate_missing': f"""
## 🚨 Infrastructure Issue: Quality Gate Not Configured

**Project**: {project_name}
**Issue**: Quality gate configuration is missing

### Required Actions:
1. **Configure Quality Gate** in SonarQube admin panel
2. **Set Quality Conditions** (coverage, duplications, etc.)
3. **Assign to Project**

Contact DevOps team to configure quality gates.
""",
            
            'pipeline_configuration': f"""
## 🚨 Infrastructure Issue: Pipeline Configuration Problem

**Project**: {project_name}
**Issue**: {details}

### Contact DevOps team to resolve pipeline configuration issues.
"""
        }
        
        return alerts.get(issue_type, alerts['pipeline_configuration'])
