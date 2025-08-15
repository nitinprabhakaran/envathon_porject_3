"""Configuration for Webhook Handler Service"""
from pydantic_settings import BaseSettings
from typing import List
import os

class Settings(BaseSettings):
    """Application settings"""
    
    # Service info
    service_name: str = "webhook-handler"
    version: str = "2.0.0"
    port: int = 8080
    log_level: str = "INFO"
    
    # Database
    database_url: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/cicd_assistant")
    db_pool_size: int = 20
    db_max_overflow: int = 40
    
    # Queue settings (RabbitMQ or SQS)
    queue_type: str = os.getenv("QUEUE_TYPE", "rabbitmq")  # 'rabbitmq' or 'sqs'
    rabbitmq_url: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
    sqs_queue_url: str = os.getenv("SQS_QUEUE_URL", "")
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    
    # Redis cache
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    cache_ttl: int = 3600
    
    # Security
    webhook_auth_enabled: bool = os.getenv("WEBHOOK_AUTH_ENABLED", "true").lower() == "true"
    gitlab_webhook_secret: str = os.getenv("GITLAB_WEBHOOK_SECRET", "your-gitlab-webhook-secret")
    sonarqube_webhook_secret: str = os.getenv("SONARQUBE_WEBHOOK_SECRET", "your-sonarqube-webhook-secret")
    api_key_header: str = "X-API-Key"
    api_keys: List[str] = os.getenv("API_KEYS", "").split(",") if os.getenv("API_KEYS") else []
    
    # Subscription settings
    subscription_callback_url: str = os.getenv("SUBSCRIPTION_CALLBACK_URL", "http://webhook-handler:8080/webhooks")
    subscription_timeout_hours: int = 24
    max_webhooks_per_project: int = 10
    
    # Session settings
    session_timeout_minutes: int = 60
    max_sessions_per_project: int = 50
    
    # CORS
    cors_origins: List[str] = ["*"]
    
    # Strands Agent URL (for direct communication if needed)
    strands_agent_url: str = os.getenv("STRANDS_AGENT_URL", "http://strands-agent:8000")
    
    class Config:
        env_file = ".env"
        case_sensitive = False

# Initialize settings
settings = Settings()