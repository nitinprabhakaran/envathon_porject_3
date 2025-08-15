"""Configuration for Webhook Handler Service"""
from pydantic_settings import BaseSettings
from typing import List, Optional

class Settings(BaseSettings):
    """Application settings with AWS service endpoints"""
    
    # Service Configuration
    service_name: str = "webhook-handler"
    port: int = 8080
    environment: str = "development"
    log_level: str = "INFO"
    
    # Database Configuration (RDS)
    database_url: str = "postgresql://user:pass@localhost/webhooks"
    database_pool_size: int = 10
    database_max_overflow: int = 20
    
    # Redis Configuration (ElastiCache)
    redis_url: str = "redis://localhost:6379"
    redis_ttl: int = 3600
    
    # AWS OpenSearch Configuration
    opensearch_endpoint: str = "https://search-domain.region.es.amazonaws.com"
    opensearch_index: str = "cicd-fixes"
    opensearch_username: Optional[str] = None
    opensearch_password: Optional[str] = None
    aws_region: str = "us-east-1"
    
    # Agent Service Configuration
    agent_service_url: str = "http://strands-agent:8000"
    agent_service_timeout: int = 60
    
    # GitLab Configuration
    gitlab_url: str = "https://gitlab.com"
    gitlab_token: str = ""
    gitlab_webhook_secret: str = ""
    
    # SonarQube Configuration
    sonarqube_url: str = "http://sonarqube:9000"
    sonarqube_token: str = ""
    sonarqube_webhook_secret: str = ""
    
    # Webhook Security
    webhook_auth_enabled: bool = True
    webhook_hmac_secret: str = "change-me-in-production"
    api_key_header: str = "X-API-Key"
    
    # Subscription Settings
    subscription_callback_url: str = "https://webhook-handler.example.com/webhooks"
    subscription_auto_cleanup: bool = True
    subscription_ttl_days: int = 90
    
    # Event Processing
    event_queue_size: int = 1000
    event_batch_size: int = 10
    event_retry_max: int = 3
    event_retry_delay: int = 5
    
    # Session Management
    session_timeout_minutes: int = 240
    max_fix_attempts: int = 5
    
    # CORS
    cors_origins: List[str] = ["*"]
    
    # Feature Flags
    enable_vector_storage: bool = True
    enable_auto_retry: bool = True
    enable_metrics: bool = True
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()