"""Context extraction utility for webhook data and session context"""
from typing import Dict, Any, Optional, List
from datetime import datetime
import json
from utils.logger import log


class ContextExtractor:
    """Extracts and formats essential context information for LLM agents"""
    
    @staticmethod
    def extract_pipeline_context(webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract pipeline failure context from GitLab webhook data"""
        try:
            project = webhook_data.get("project", {})
            pipeline = webhook_data.get("object_attributes", {})
            builds = webhook_data.get("builds", [])
            
            # Extract basic project information
            context = {
                "project_id": str(project.get("id", "Unknown")),
                "project_name": project.get("name", "Unknown"),
                "project_path": project.get("path_with_namespace", "Unknown"),
                "project_url": project.get("web_url", ""),
                "default_branch": project.get("default_branch", "main"),
            }
            
            # Extract pipeline information
            context.update({
                "pipeline_id": str(pipeline.get("id", "Unknown")),
                "pipeline_url": pipeline.get("url", ""),
                "pipeline_status": pipeline.get("status", "failed"),
                "branch": pipeline.get("ref", "Unknown"),
                "commit_sha": pipeline.get("sha", "")[:8] if pipeline.get("sha") else "",
                "commit_message": webhook_data.get("commit", {}).get("message", ""),
                "commit_author": webhook_data.get("commit", {}).get("author", {}).get("name", ""),
                "created_at": pipeline.get("created_at", ""),
                "finished_at": pipeline.get("finished_at", ""),
            })
            
            # Extract failed jobs information
            failed_jobs = [job for job in builds if job.get("status") == "failed"]
            passed_jobs = [job for job in builds if job.get("status") == "success"]
            
            if failed_jobs:
                # Sort by finished_at to get the most recent failure
                failed_jobs.sort(key=lambda x: x.get("finished_at", ""), reverse=True)
                most_recent_failed = failed_jobs[0]
                
                context.update({
                    "failed_job_count": len(failed_jobs),
                    "most_recent_failed_job": {
                        "id": str(most_recent_failed.get("id", "")),
                        "name": most_recent_failed.get("name", ""),
                        "stage": most_recent_failed.get("stage", ""),
                        "status": most_recent_failed.get("status", ""),
                        "started_at": most_recent_failed.get("started_at", ""),
                        "finished_at": most_recent_failed.get("finished_at", ""),
                        "duration": most_recent_failed.get("duration"),
                        "runner_description": most_recent_failed.get("runner", {}).get("description", ""),
                    },
                    "all_failed_jobs": [
                        {
                            "id": str(job.get("id", "")),
                            "name": job.get("name", ""),
                            "stage": job.get("stage", ""),
                            "finished_at": job.get("finished_at", "")
                        }
                        for job in failed_jobs
                    ]
                })
            
            context.update({
                "passed_job_count": len(passed_jobs),
                "total_job_count": len(builds)
            })
            
            # Determine failure type based on job names
            failure_types = []
            for job in failed_jobs:
                job_name = job.get("name", "").lower()
                if any(keyword in job_name for keyword in ["test", "spec", "unit"]):
                    failure_types.append("test")
                elif any(keyword in job_name for keyword in ["build", "compile"]):
                    failure_types.append("build")
                elif any(keyword in job_name for keyword in ["deploy", "deployment"]):
                    failure_types.append("deployment")
                elif any(keyword in job_name for keyword in ["sonar", "quality", "lint"]):
                    failure_types.append("quality")
                elif any(keyword in job_name for keyword in ["security", "scan"]):
                    failure_types.append("security")
                else:
                    failure_types.append("other")
            
            context["likely_failure_types"] = list(set(failure_types))
            
            return context
            
        except Exception as e:
            log.error(f"Error extracting pipeline context: {e}")
            return {"error": f"Failed to extract context: {str(e)}"}
    
    @staticmethod
    def extract_quality_context(webhook_data: Dict[str, Any], sonarqube_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Extract quality analysis context from webhook and SonarQube data"""
        try:
            # Start with pipeline context if this comes from a pipeline failure
            if webhook_data.get("object_kind") == "pipeline":
                context = ContextExtractor.extract_pipeline_context(webhook_data)
                context["source"] = "pipeline_failure"
            else:
                # Direct SonarQube webhook
                project = webhook_data.get("project", {})
                context = {
                    "sonarqube_key": project.get("key", "Unknown"),
                    "project_name": project.get("name", "Unknown"),
                    "source": "sonarqube_webhook"
                }
            
            # Extract quality gate information
            quality_gate = webhook_data.get("qualityGate", {})
            if quality_gate:
                context.update({
                    "quality_gate_status": quality_gate.get("status", "ERROR"),
                    "quality_gate_name": quality_gate.get("name", ""),
                    "quality_gate_conditions": []
                })
                
                # Extract failed conditions
                for condition in quality_gate.get("conditions", []):
                    if condition.get("status") == "ERROR":
                        context["quality_gate_conditions"].append({
                            "metric": condition.get("metricKey", ""),
                            "operator": condition.get("operator", ""),
                            "threshold": condition.get("errorThreshold", ""),
                            "actual_value": condition.get("value", ""),
                            "status": condition.get("status", "")
                        })
            
            # Add SonarQube-specific data if provided
            if sonarqube_data:
                context.update({
                    "sonarqube_analysis": sonarqube_data
                })
            
            return context
            
        except Exception as e:
            log.error(f"Error extracting quality context: {e}")
            return {"error": f"Failed to extract context: {str(e)}"}
    
    @staticmethod
    def format_context_for_prompt(context: Dict[str, Any], agent_type: str) -> str:
        """Format extracted context into a clear prompt section"""
        try:
            if context.get("error"):
                return f"**Context Extraction Error**: {context['error']}"
            
            if agent_type == "pipeline":
                return ContextExtractor._format_pipeline_context(context)
            elif agent_type == "quality":
                return ContextExtractor._format_quality_context(context)
            else:
                return "**Unknown agent type for context formatting**"
                
        except Exception as e:
            log.error(f"Error formatting context: {e}")
            return f"**Context Formatting Error**: {str(e)}"
    
    @staticmethod
    def _format_pipeline_context(context: Dict[str, Any]) -> str:
        """Format pipeline context for LLM prompt"""
        sections = []
        
        # Project Information
        sections.append("## 📋 Project Information")
        sections.append(f"- **Project**: {context.get('project_name')} (ID: {context.get('project_id')})")
        sections.append(f"- **Repository**: {context.get('project_path')}")
        sections.append(f"- **Default Branch**: {context.get('default_branch')}")
        if context.get('project_url'):
            sections.append(f"- **Project URL**: {context.get('project_url')}")
        
        # Pipeline Information
        sections.append("\n## 🔄 Pipeline Information")
        sections.append(f"- **Pipeline ID**: {context.get('pipeline_id')}")
        sections.append(f"- **Status**: {context.get('pipeline_status')}")
        sections.append(f"- **Branch**: {context.get('branch')}")
        if context.get('commit_sha'):
            sections.append(f"- **Commit**: {context.get('commit_sha')}")
        if context.get('commit_message'):
            sections.append(f"- **Commit Message**: {context.get('commit_message')}")
        if context.get('commit_author'):
            sections.append(f"- **Author**: {context.get('commit_author')}")
        if context.get('pipeline_url'):
            sections.append(f"- **Pipeline URL**: {context.get('pipeline_url')}")
        
        # Timing Information
        if context.get('created_at') or context.get('finished_at'):
            sections.append("\n## ⏱️ Timing")
            if context.get('created_at'):
                sections.append(f"- **Started**: {context.get('created_at')}")
            if context.get('finished_at'):
                sections.append(f"- **Finished**: {context.get('finished_at')}")
        
        # Job Status Summary
        sections.append("\n## 📊 Job Status Summary")
        sections.append(f"- **Total Jobs**: {context.get('total_job_count', 0)}")
        sections.append(f"- **Failed Jobs**: {context.get('failed_job_count', 0)}")
        sections.append(f"- **Passed Jobs**: {context.get('passed_job_count', 0)}")
        
        if context.get('likely_failure_types'):
            sections.append(f"- **Likely Failure Types**: {', '.join(context.get('likely_failure_types', []))}")
        
        # Most Recent Failed Job Details
        if context.get('most_recent_failed_job'):
            job = context['most_recent_failed_job']
            sections.append("\n## ❌ Most Recent Failed Job")
            sections.append(f"- **Job Name**: {job.get('name')}")
            sections.append(f"- **Job ID**: {job.get('id')}")
            sections.append(f"- **Stage**: {job.get('stage')}")
            if job.get('started_at'):
                sections.append(f"- **Started**: {job.get('started_at')}")
            if job.get('finished_at'):
                sections.append(f"- **Finished**: {job.get('finished_at')}")
            if job.get('duration'):
                sections.append(f"- **Duration**: {job.get('duration')} seconds")
            if job.get('runner_description'):
                sections.append(f"- **Runner**: {job.get('runner_description')}")
        
        # All Failed Jobs List
        if context.get('all_failed_jobs') and len(context.get('all_failed_jobs', [])) > 1:
            sections.append("\n## 📝 All Failed Jobs")
            for i, job in enumerate(context.get('all_failed_jobs', []), 1):
                sections.append(f"{i}. **{job.get('name')}** (ID: {job.get('id')}) - Stage: {job.get('stage')}")
        
        # Analysis Instructions
        sections.append("\n## 🔍 Analysis Instructions")
        sections.append("Use the above context to:")
        sections.append("1. **Retrieve logs** for the failed job(s) using the Job IDs provided")
        sections.append("2. **Examine relevant files** in the project repository")
        sections.append("3. **Analyze the failure patterns** based on the job names and stages")
        sections.append("4. **Provide specific solutions** targeting the identified failure types")
        
        return "\n".join(sections)
    
    @staticmethod
    def _format_quality_context(context: Dict[str, Any]) -> str:
        """Format quality context for LLM prompt"""
        sections = []
        
        # Source Information
        if context.get('source') == 'pipeline_failure':
            sections.append("## 📋 Source: Pipeline Quality Gate Failure")
            sections.append(f"- **Project**: {context.get('project_name')} (ID: {context.get('project_id')})")
            sections.append(f"- **Repository**: {context.get('project_path')}")
            sections.append(f"- **Pipeline ID**: {context.get('pipeline_id')}")
            sections.append(f"- **Branch**: {context.get('branch')}")
            if context.get('most_recent_failed_job'):
                job = context['most_recent_failed_job']
                sections.append(f"- **Failed Quality Job**: {job.get('name')} (ID: {job.get('id')})")
        else:
            sections.append("## 📋 Source: Direct SonarQube Webhook")
            sections.append(f"- **SonarQube Project**: {context.get('sonarqube_key')}")
            sections.append(f"- **Project Name**: {context.get('project_name')}")
        
        # Quality Gate Information
        if context.get('quality_gate_status'):
            sections.append("\n## 🚪 Quality Gate Status")
            sections.append(f"- **Status**: {context.get('quality_gate_status')}")
            if context.get('quality_gate_name'):
                sections.append(f"- **Gate Name**: {context.get('quality_gate_name')}")
            
            # Failed Conditions
            if context.get('quality_gate_conditions'):
                sections.append("\n### ❌ Failed Conditions")
                for i, condition in enumerate(context.get('quality_gate_conditions', []), 1):
                    sections.append(f"{i}. **{condition.get('metric')}**: {condition.get('actual_value')} {condition.get('operator')} {condition.get('threshold')}")
        
        # SonarQube Analysis Data
        if context.get('sonarqube_analysis'):
            analysis = context['sonarqube_analysis']
            sections.append("\n## 📊 SonarQube Analysis Summary")
            
            if isinstance(analysis, dict):
                # Format metrics and issues from analysis
                if 'total_issues' in analysis:
                    sections.append(f"- **Total Issues**: {analysis.get('total_issues', 0)}")
                if 'bug_count' in analysis:
                    sections.append(f"- **Bugs**: {analysis.get('bug_count', 0)}")
                if 'vulnerability_count' in analysis:
                    sections.append(f"- **Vulnerabilities**: {analysis.get('vulnerability_count', 0)}")
                if 'code_smell_count' in analysis:
                    sections.append(f"- **Code Smells**: {analysis.get('code_smell_count', 0)}")
                if 'critical_issues' in analysis:
                    sections.append(f"- **Critical/Blocker Issues**: {analysis.get('critical_issues', 0)}")
                if 'coverage' in analysis:
                    sections.append(f"- **Coverage**: {analysis.get('coverage', 'N/A')}%")
        
        # Analysis Instructions
        sections.append("\n## 🔍 Analysis Instructions")
        sections.append("Use the above context to:")
        
        if context.get('sonarqube_key'):
            sections.append(f"1. **Retrieve detailed issues** from SonarQube project: `{context.get('sonarqube_key')}`")
        else:
            sections.append("1. **Retrieve SonarQube project** information and detailed issues")
        
        sections.append("2. **Analyze quality metrics** and identify the most critical issues")
        sections.append("3. **Examine affected files** and understand the code quality problems")
        sections.append("4. **Prioritize fixes** based on severity and impact")
        sections.append("5. **Provide comprehensive solutions** to improve code quality")
        
        return "\n".join(sections)
    
    @staticmethod
    def extract_session_context(session_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract relevant context from session data"""
        try:
            context = {
                "session_id": session_data.get("id"),
                "session_type": session_data.get("session_type"),
                "project_id": session_data.get("project_id"),
                "status": session_data.get("status"),
                "created_at": session_data.get("created_at"),
            }
            
            # Extract metadata
            metadata = session_data.get("metadata", {})
            if metadata:
                context.update({
                    "project_name": metadata.get("project_name"),
                    "pipeline_id": metadata.get("pipeline_id"),
                    "branch": metadata.get("branch"),
                    "current_fix_branch": metadata.get("current_fix_branch"),
                    "sonarqube_key": metadata.get("sonarqube_key"),
                })
            
            # Extract fix attempts
            fix_attempts = session_data.get("fix_attempts", [])
            if fix_attempts:
                context["fix_attempts"] = [
                    {
                        "attempt_number": attempt.get("attempt_number"),
                        "branch_name": attempt.get("branch_name"),
                        "status": attempt.get("status"),
                        "created_at": attempt.get("created_at"),
                        "merge_request_url": attempt.get("merge_request_url"),
                    }
                    for attempt in fix_attempts
                ]
            
            # Extract tracked files
            tracked_files = session_data.get("tracked_files", [])
            if tracked_files:
                context["tracked_files"] = [
                    {
                        "file_path": tf.get("file_path"),
                        "status": tf.get("status"),
                        "accessed_at": tf.get("accessed_at"),
                    }
                    for tf in tracked_files
                ]
            
            return context
            
        except Exception as e:
            log.error(f"Error extracting session context: {e}")
            return {"error": f"Failed to extract session context: {str(e)}"}
    
    @staticmethod
    def create_context_tool(session_id: str, webhook_data: Dict[str, Any], agent_type: str):
        """Create a tool that provides formatted context to the agent"""
        from strands import tool
        
        # Extract context once
        if agent_type == "pipeline":
            context = ContextExtractor.extract_pipeline_context(webhook_data)
        else:  # quality
            context = ContextExtractor.extract_quality_context(webhook_data)
        
        formatted_context = ContextExtractor.format_context_for_prompt(context, agent_type)
        
        @tool
        def get_failure_context() -> str:
            """Get comprehensive context about the current failure including project details, pipeline/quality information, and analysis guidance.
            
            This tool provides all the essential information you need to start your analysis:
            - Project and repository details
            - Pipeline or quality gate information  
            - Failed job details with IDs for log retrieval
            - Specific guidance on what to analyze
            
            Use this tool first to understand the failure context before using other tools.
            """
            return formatted_context
        
        return get_failure_context
