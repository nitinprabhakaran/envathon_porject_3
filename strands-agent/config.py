import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    """Application configuration"""
    
    # LLM Settings
    llm_provider: str = "bedrock"
    anthropic_api_key: Optional[str] = None
    aws_region: str = "us-west-2"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_session_token: Optional[str] = None
    max_log_size: int = 30000
    
    # Database
    database_url: str = "postgresql://cicd_user:secure_password@postgres-assistant:5432/cicd_assistant"
    
    # GitLab
    gitlab_url: str = "http://gitlab:80"
    gitlab_token: str = ""
    
    # SonarQube
    sonar_host_url: str = "http://sonarqube:9000"
    sonar_token: str = ""
    
    # App Settings
    log_level: str = "INFO"
    session_timeout_minutes: int = 180
    port: int = 8000
    max_fix_attempts: int = 5
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()