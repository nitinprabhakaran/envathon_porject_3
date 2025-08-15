"""Unified configuration with local/AWS switching"""
import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    """Application configuration with environment-based service switching"""
    
    # Deployment Environment
    deployment_mode: str = "local"  # "local" or "aws"
    environment: str = "development"
    log_level: str = "INFO"
    port: int = 8000
    
    # Database Configuration (switches between local/RDS)
    db_type: str = "local"  # "local" or "rds"
    
    # Local PostgreSQL
    local_db_url: str = "postgresql://cicd_assistant:secure_password@postgres-assistant:5432/cicd_assistant"
    
    # AWS RDS
    rds_endpoint: str = ""
    rds_port: int = 5432
    rds_database: str = "cicd_assistant"
    rds_username: str = ""
    rds_password: str = ""
    
    @property
    def database_url(self) -> str:
        """Get database URL based on deployment mode"""
        if self.db_type == "rds" and self.rds_endpoint:
            return f"postgresql://{self.rds_username}:{self.rds_password}@{self.rds_endpoint}:{self.rds_port}/{self.rds_database}"
        return self.local_db_url
    
    # Queue Configuration (switches between RabbitMQ/Redis/SQS)
    queue_type: str = "rabbitmq"  # "rabbitmq", "redis", or "sqs"
    
    # Local Queue Options
    rabbitmq_url: str = "amqp://admin:admin@rabbitmq:5672"
    redis_url: str = "redis://redis:6379"
    queue_name: str = "webhook-events"
    
    # AWS SQS
    sqs_queue_url: str = ""
    sqs_region: str = "us-east-1"
    
    # Vector Store Configuration (switches between local OpenSearch/AWS OpenSearch)
    vector_store_type: str = "local"  # "local" or "aws"
    
    # Local OpenSearch
    local_opensearch_endpoint: str = "http://opensearch:9200"
    
    # AWS OpenSearch
    aws_opensearch_endpoint: str = ""
    aws_opensearch_region: str = "us-east-1"
    
    opensearch_index: str = "cicd-fixes"
    opensearch_username: Optional[str] = None
    opensearch_password: Optional[str] = None
    
    @property
    def opensearch_endpoint(self) -> str:
        """Get OpenSearch endpoint based on deployment mode"""
        if self.vector_store_type == "aws" and self.aws_opensearch_endpoint:
            return self.aws_opensearch_endpoint
        return self.local_opensearch_endpoint
    
    # AWS Credentials (used when deployment_mode = "aws")
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_session_token: Optional[str] = None
    aws_region: str = "us-east-1"
    
    # LLM Configuration
    llm_provider: str = "bedrock"
    model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    anthropic_api_key: Optional[str] = None
    max_log_size: int = 30000
    
    # GitLab Configuration
    gitlab_url: str = "http://gitlab:80"
    gitlab_token: str = ""
    
    # SonarQube Configuration
    sonar_host_url: str = "http://sonarqube:9000"
    sonar_token: str = ""
    
    # Processing Configuration
    session_timeout_minutes: int = 240
    max_fix_attempts: int = 5
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()