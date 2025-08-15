"""Configuration for Strands Agent Service"""
from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    """Application settings"""
    
    # Service info
    service_name: str = "strands-agent"
    version: str = "2.0.0"
    port: int = 8000
    log_level: str = "INFO"
    
    # Database
    database_url: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/cicd_assistant")
    db_pool_size: int = 20
    
    # Queue settings
    queue_type: str = os.getenv("QUEUE_TYPE", "none")  # 'rabbitmq', 'sqs', or 'none'
    rabbitmq_url: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
    sqs_queue_url: str = os.getenv("SQS_QUEUE_URL", "")
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    
    # OpenSearch/ElasticSearch for Vector Store
    opensearch_host: str = os.getenv("OPENSEARCH_HOST", "opensearch")
    opensearch_port: int = 9200
    opensearch_user: str = os.getenv("OPENSEARCH_USER", "admin")
    opensearch_password: str = os.getenv("OPENSEARCH_PASSWORD", "admin")
    opensearch_use_ssl: bool = os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true"
    
    # AWS Bedrock
    llm_provider: str = os.getenv("LLM_PROVIDER", "bedrock")
    bedrock_model_id: str = os.getenv("MODEL_ID", "us.anthropic.claude-3-5-sonnet-20241022-v2:0")
    bedrock_region: str = os.getenv("AWS_REGION", "us-east-2")
    aws_access_key_id: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    aws_session_token: str = os.getenv("AWS_SESSION_TOKEN", "")
    
    # GitLab
    gitlab_url: str = os.getenv("GITLAB_URL", "http://gitlab")
    gitlab_token: str = os.getenv("GITLAB_TOKEN", "")
    
    # SonarQube
    sonarqube_url: str = os.getenv("SONARQUBE_URL", "http://sonarqube:9000")
    sonarqube_token: str = os.getenv("SONARQUBE_TOKEN", "")
    
    # Session settings
    session_timeout_minutes: int = 60
    max_retries: int = 3
    max_fix_attempts: int = 3
    
    # Vector store settings
    vector_index_name: str = "cicd_fixes"
    vector_dimension: int = 768
    max_similar_results: int = 5
    
    # Log processing settings
    max_log_size: int = 30000
    max_log_lines: int = 1000
    
    class Config:
        env_file = ".env"
        case_sensitive = False

# Initialize settings
settings = Settings()