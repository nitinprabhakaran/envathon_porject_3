"""Unified configuration manager compatible with existing .env.example structure"""
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class ServiceConfig:
    """Service configuration structure"""
    host: str
    port: int
    url: str
    timeout: int = 30
    retries: int = 3

class ConfigurationManager:
    """Central configuration manager eliminating all hardcoded values
    Compatible with existing .env.example structure"""
    
    def __init__(self):
        self.environment = os.getenv("ENVIRONMENT", "local")
        self.deployment_target = os.getenv("DEPLOYMENT_TARGET", "docker-compose")
        
        # Load all configurations
        self._database_config = self._load_database_config()
        self._service_configs = self._load_service_configs()
        self._queue_config = self._load_queue_config()
        self._llm_config = self._load_llm_config()
        self._feature_flags = self._load_feature_flags()
        self._auth_config = self._load_auth_config()
        self._session_config = self._load_session_config()
    
    def _load_database_config(self) -> Dict[str, Any]:
        """Load database configuration compatible with existing env structure"""
        return {
            "url": os.getenv("DATABASE_URL", "postgresql://cicd_assistant:secure_password@postgres-assistant:5432/cicd_assistant"),
            "host": os.getenv("DB_HOST", "postgres-assistant"),
            "port": int(os.getenv("DB_PORT", "5432")),
            "name": os.getenv("DB_NAME", "cicd_assistant"),
            "user": os.getenv("DB_USER", "cicd_assistant"),
            "password": os.getenv("DB_PASSWORD", "secure_password"),
            "pool_size": int(os.getenv("DB_POOL_MAX_SIZE", "10")),
            "min_pool_size": int(os.getenv("DB_POOL_MIN_SIZE", "2")),
            "max_overflow": 20,  # Reasonable default
            "pool_timeout": 30,
            "pool_recycle": 3600,
        }
    
    def _load_service_configs(self) -> Dict[str, ServiceConfig]:
        """Load service configurations using existing env variables"""
        # Use existing port variables from your .env.example
        webhook_port = int(os.getenv("WEBHOOK_HANDLER_PORT", "8090"))
        strands_port = int(os.getenv("STRANDS_AGENT_PORT", "8000"))
        streamlit_port = int(os.getenv("STREAMLIT_PORT", "8501"))
        
        return {
            "webhook_handler": ServiceConfig(
                host=os.getenv("WEBHOOK_HANDLER_HOST", "webhook-handler"),
                port=webhook_port,
                url=f"http://webhook-handler:{webhook_port}",
                timeout=30,
                retries=3
            ),
            "strands_agent": ServiceConfig(
                host=os.getenv("STRANDS_AGENT_HOST", "strands-agent"),
                port=strands_port,
                url=f"http://strands-agent:{strands_port}",
                timeout=60,
                retries=3
            ),
            "streamlit_ui": ServiceConfig(
                host=os.getenv("STREAMLIT_HOST", "streamlit-ui"),
                port=streamlit_port,
                url=f"http://streamlit-ui:{streamlit_port}",
                timeout=30,
                retries=3
            )
        }
    
    def _load_queue_config(self) -> Dict[str, Any]:
        """Load queue configuration using existing env structure"""
        queue_type = os.getenv("QUEUE_TYPE", "rabbitmq")
        
        config = {
            "type": queue_type,
            "name": os.getenv("QUEUE_NAME", "webhook-events"),
            "max_size": 1000,
            "workers": 2,
        }
        
        if queue_type == "rabbitmq":
            config.update({
                "url": os.getenv("RABBITMQ_URL", "amqp://admin:admin@rabbitmq:5672"),
                "exchange": "webhook-events",
                "routing_key": "webhook"
            })
        elif queue_type == "redis":
            config.update({
                "url": os.getenv("REDIS_URL", "redis://redis:6379/0"),
                "key_prefix": "webhook:"
            })
        elif queue_type == "sqs":
            config.update({
                "url": os.getenv("SQS_QUEUE_URL", ""),
                "region": os.getenv("SQS_REGION", "us-east-1")
            })
        
        return config
    
    def _load_llm_config(self) -> Dict[str, Any]:
        """Load LLM configuration from existing env structure"""
        return {
            "provider": os.getenv("LLM_PROVIDER", "bedrock"),
            "model_id": os.getenv("MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"),
            "aws_region": os.getenv("AWS_REGION", "us-east-1"),
            "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
            "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
            "temperature": 0.1,
            "max_tokens": 4096
        }
    
    def _load_feature_flags(self) -> Dict[str, bool]:
        """Load feature flags from existing env structure"""
        return {
            "vector_store": self._get_bool_env("ENABLE_VECTOR_STORE", True),
            "queue_processing": self._get_bool_env("ENABLE_QUEUE_PROCESSING", True),
            "webhook_auth": self._get_bool_env("ENABLE_WEBHOOK_AUTH", True),
            "cors": self._get_bool_env("ENABLE_CORS", True),
            "caching": True,  # Always enable for performance
            "metrics": True,
            "async_processing": True,
            "tool_autodiscovery": True,
        }
    
    def _load_auth_config(self) -> Dict[str, Any]:
        """Load authentication configuration"""
        return {
            "gitlab_token": os.getenv("GITLAB_TOKEN", ""),
            "gitlab_url": os.getenv("GITLAB_URL", "http://gitlab:80"),
            "gitlab_webhook_secret": os.getenv("GITLAB_WEBHOOK_SECRET", ""),
            "sonar_token": os.getenv("SONAR_TOKEN", ""),
            "sonar_url": os.getenv("SONAR_HOST_URL", "http://sonarqube:9000"),
            "sonar_webhook_secret": os.getenv("SONARQUBE_WEBHOOK_SECRET", ""),
            "webhook_hmac_secret": os.getenv("WEBHOOK_HMAC_SECRET", ""),
            "cors_origins": os.getenv("CORS_ORIGINS", "*").split(",")
        }
    
    def _load_session_config(self) -> Dict[str, Any]:
        """Load session management configuration"""
        return {
            "timeout_minutes": int(os.getenv("SESSION_TIMEOUT_MINUTES", "240")),
            "max_sessions_per_project": int(os.getenv("MAX_SESSIONS_PER_PROJECT", "50")),
            "max_fix_attempts": int(os.getenv("MAX_FIX_ATTEMPTS", "3")),
            "max_log_size": int(os.getenv("MAX_LOG_SIZE", "30000")),
            "max_log_lines": int(os.getenv("MAX_LOG_LINES", "1000"))
        }
    
    def _get_bool_env(self, key: str, default: bool = False) -> bool:
        """Convert environment variable to boolean"""
        value = os.getenv(key, str(default)).lower()
        return value in ("true", "1", "yes", "on")
    
    # Property accessors for easy use
    @property
    def database_config(self) -> Dict[str, Any]:
        return self._database_config
    
    @property
    def queue_config(self) -> Dict[str, Any]:
        return self._queue_config
    
    @property
    def llm_config(self) -> Dict[str, Any]:
        return self._llm_config
    
    @property
    def feature_flags(self) -> Dict[str, bool]:
        return self._feature_flags
    
    @property
    def auth_config(self) -> Dict[str, Any]:
        return self._auth_config
    
    @property
    def session_config(self) -> Dict[str, Any]:
        return self._session_config
    
    def get_service_url(self, service_name: str) -> str:
        """Get service URL by name"""
        if service_name in self._service_configs:
            return self._service_configs[service_name].url
        return ""
    
    def get_service_config(self, service_name: str) -> Optional[ServiceConfig]:
        """Get full service configuration"""
        return self._service_configs.get(service_name)
    
    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if feature is enabled"""
        return self._feature_flags.get(feature_name, False)
    
    def get_log_level(self) -> str:
        """Get logging level"""
        return os.getenv("LOG_LEVEL", "INFO").upper()
