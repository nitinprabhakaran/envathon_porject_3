"""Configuration for Webhook Handler Service"""
from pydantic_settings import BaseSettings
from typing import List
import os

class Settings(BaseSettings):
    """Application settings with unified configuration pattern"""
    
    # Service info
    service_name: str = "webhook-handler"
    version: str = "2.0.0"
    port: int = int(os.getenv("WEBHOOK_HANDLER_PORT", "8090"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Environment info
    environment: str = os.getenv("ENVIRONMENT", "local")
    deployment_target: str = os.getenv("DEPLOYMENT_TARGET", "docker-compose")
    
    # Database (unified configuration)
    database_url: str = os.getenv("DATABASE_URL", "postgresql://cicd_assistant:secure_password@postgres-assistant:5432/cicd_assistant")
    db_pool_min_size: int = int(os.getenv("DB_POOL_MIN_SIZE", "2"))
    db_pool_max_size: int = int(os.getenv("DB_POOL_MAX_SIZE", "10"))
    
    # Queue settings
    queue_type: str = os.getenv("QUEUE_TYPE", "rabbitmq")
    rabbitmq_url: str = os.getenv("RABBITMQ_URL", "amqp://admin:admin@rabbitmq:5672/")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    queue_name: str = os.getenv("QUEUE_NAME", "webhook-events")
    sqs_queue_url: str = os.getenv("SQS_QUEUE_URL", "")
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    
    # Security
    webhook_auth_enabled: bool = os.getenv("WEBHOOK_AUTH_ENABLED", "true").lower() == "true"
    gitlab_webhook_secret: str = os.getenv("GITLAB_WEBHOOK_SECRET", "your-gitlab-webhook-secret")
    sonarqube_webhook_secret: str = os.getenv("SONARQUBE_WEBHOOK_SECRET", "your-sonarqube-webhook-secret")
    webhook_hmac_secret: str = os.getenv("WEBHOOK_HMAC_SECRET", "your-hmac-secret")
    
    # API security
    api_key_header: str = "X-API-Key"
    api_keys_str: str = os.getenv("API_KEYS", "")
    
    @property
    def api_keys(self) -> List[str]:
        """Parse API keys from comma-separated string"""
        if not self.api_keys_str or self.api_keys_str.strip() == "":
            return []
        return [key.strip() for key in self.api_keys_str.split(",") if key.strip()]
    
    # Session settings
    session_timeout_minutes: int = int(os.getenv("SESSION_TIMEOUT_MINUTES", "240"))
    max_sessions_per_project: int = int(os.getenv("MAX_SESSIONS_PER_PROJECT", "50"))
    
    # External services
    strands_agent_url: str = os.getenv("STRANDS_AGENT_URL", "http://strands-agent:8000")
    
    # External service credentials for system-managed authentication
    gitlab_url: str = os.getenv("GITLAB_URL", "http://gitlab:80")
    gitlab_token: str = os.getenv("GITLAB_TOKEN", "")
    sonar_host_url: str = os.getenv("SONAR_HOST_URL", "http://sonarqube:9000")
    sonar_token: str = os.getenv("SONAR_TOKEN", "")
    
    # Subscription settings
    subscription_callback_url: str = os.getenv("SUBSCRIPTION_CALLBACK_URL", f"http://webhook-handler:{port}/webhooks")
    subscription_ttl_days: int = int(os.getenv("SUBSCRIPTION_TTL_DAYS", "90"))
    
    # CORS
    cors_origins_str: str = os.getenv("CORS_ORIGINS", "*")
    
    @property
    def cors_origins(self) -> List[str]:
        """Parse CORS origins from string"""
        if not self.cors_origins_str or self.cors_origins_str.strip() == "":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins_str.split(",") if origin.strip()]
    
    # Feature flags
    enable_webhook_auth: bool = os.getenv("ENABLE_WEBHOOK_AUTH", "true").lower() == "true"
    enable_cors: bool = os.getenv("ENABLE_CORS", "true").lower() == "true"
    
    class Config:
        env_file = ".env"
        case_sensitive = False

# Initialize settings
settings = Settings()