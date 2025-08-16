"""Configuration for Strands Agent Service"""
from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    """Application settings with unified configuration pattern"""
    
    # Service info
    service_name: str = "strands-agent"
    version: str = "2.0.0"
    port: int = int(os.getenv("STRANDS_AGENT_PORT", "8000"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Environment info
    environment: str = os.getenv("ENVIRONMENT", "local")
    deployment_target: str = os.getenv("DEPLOYMENT_TARGET", "docker-compose")
    
    # Database (unified configuration)
    database_url: str = os.getenv("DATABASE_URL", "postgresql://cicd_assistant:secure_password@postgres-assistant:5432/cicd_assistant")
    db_pool_min_size: int = int(os.getenv("DB_POOL_MIN_SIZE", "2"))
    db_pool_max_size: int = int(os.getenv("DB_POOL_MAX_SIZE", "10"))
    
    # Queue settings
    queue_type: str = os.getenv("QUEUE_TYPE", "none")
    rabbitmq_url: str = os.getenv("RABBITMQ_URL", "amqp://admin:admin@rabbitmq:5672/")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    queue_name: str = os.getenv("QUEUE_NAME", "webhook-events")
    sqs_queue_url: str = os.getenv("SQS_QUEUE_URL", "")
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    
    # Vector Store configuration
    vector_store_type: str = os.getenv("VECTOR_STORE_TYPE", "opensearch-local")
    opensearch_host: str = os.getenv("OPENSEARCH_HOST", "opensearch")
    opensearch_port: int = int(os.getenv("OPENSEARCH_PORT", "9200"))
    opensearch_username: str = os.getenv("OPENSEARCH_USERNAME", "")
    opensearch_password: str = os.getenv("OPENSEARCH_PASSWORD", "")
    opensearch_use_ssl: bool = os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true"
    opensearch_index: str = os.getenv("OPENSEARCH_INDEX", "cicd-fixes")
    
    # AWS services
    aws_access_key_id: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    aws_session_token: str = os.getenv("AWS_SESSION_TOKEN", "")
    
    # LLM Configuration
    llm_provider: str = os.getenv("LLM_PROVIDER", "bedrock")
    model_id: str = os.getenv("MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    
    # External Services
    gitlab_url: str = os.getenv("GITLAB_URL", "http://gitlab")
    gitlab_token: str = os.getenv("GITLAB_TOKEN", "")
    sonarqube_url: str = os.getenv("SONAR_HOST_URL", "http://sonarqube:9000")
    sonarqube_token: str = os.getenv("SONAR_TOKEN", "")
    
    # Session settings
    session_timeout_minutes: int = int(os.getenv("SESSION_TIMEOUT_MINUTES", "240"))
    max_sessions_per_project: int = int(os.getenv("MAX_SESSIONS_PER_PROJECT", "50"))
    max_retries: int = 3
    max_fix_attempts: int = int(os.getenv("MAX_FIX_ATTEMPTS", "3"))
    
    # Processing settings
    max_log_size: int = int(os.getenv("MAX_LOG_SIZE", "30000"))
    max_log_lines: int = int(os.getenv("MAX_LOG_LINES", "1000"))
    
    # Vector store settings
    vector_dimension: int = 768
    max_similar_results: int = 5
    
    # Feature flags
    enable_vector_store: bool = os.getenv("ENABLE_VECTOR_STORE", "true").lower() == "true"
    enable_queue_processing: bool = os.getenv("ENABLE_QUEUE_PROCESSING", "true").lower() == "true"
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "allow"  # Allow extra environment variables

# Initialize settings
settings = Settings()