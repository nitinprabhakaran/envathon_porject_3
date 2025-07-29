"""Database models and data structures"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class SessionContext:
    """Complete session context for agent invocations"""
    session_id: str
    session_type: str  # 'pipeline' or 'quality'
    project_id: str
    project_name: str
    
    # Pipeline specific
    pipeline_id: Optional[str] = None
    pipeline_url: Optional[str] = None
    branch: Optional[str] = None
    commit_sha: Optional[str] = None
    failed_stage: Optional[str] = None
    job_name: Optional[str] = None
    
    # Quality specific
    sonarqube_key: Optional[str] = None
    quality_gate_status: Optional[str] = None
    gitlab_project_id: Optional[str] = None
    
    # Common
    created_at: Optional[datetime] = None
    webhook_data: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for agent usage"""
        result = {}
        for k, v in asdict(self).items():
            if v is not None:
                if isinstance(v, datetime):
                    result[k] = v.isoformat()
                else:
                    result[k] = v
        return result

@dataclass
class HistoricalFix:
    """Historical fix information"""
    error_signature: str
    fix_description: str
    fix_content: Dict[str, str]  # file_path -> content
    success_rate: float
    last_applied: datetime
    application_count: int
    projects_fixed: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "error_signature": self.error_signature,
            "fix_description": self.fix_description,
            "fix_content": self.fix_content,
            "success_rate": self.success_rate,
            "last_applied": self.last_applied.isoformat() if isinstance(self.last_applied, datetime) else self.last_applied,
            "application_count": self.application_count,
            "projects_fixed": self.projects_fixed
        }