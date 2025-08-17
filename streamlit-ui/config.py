"""Configuration for Streamlit UI"""
import os

class UISettings:
    """UI-specific settings that mirror the agent configuration for consistency"""
    
    # Branch naming configuration - simplified to 2 categories only
    branch_prefix_pipeline: str = os.getenv("BRANCH_PREFIX_PIPELINE", "fix/pipeline_")
    branch_prefix_quality: str = os.getenv("BRANCH_PREFIX_QUALITY", "fix/sonarqube_")
    
    # API settings
    agent_api_url: str = os.getenv("AGENT_API_URL", "http://strands-agent:8000")
    
    # Timeout settings
    api_timeout_seconds: int = int(os.getenv("API_TIMEOUT_SECONDS", "120"))
    session_details_timeout: int = int(os.getenv("SESSION_DETAILS_TIMEOUT", "30"))
    default_request_timeout: int = int(os.getenv("DEFAULT_REQUEST_TIMEOUT", "10"))
    
    # UI settings
    refresh_interval: int = int(os.getenv("UI_REFRESH_INTERVAL", "30"))
    max_sessions_display: int = int(os.getenv("UI_MAX_SESSIONS_DISPLAY", "50"))

# Initialize settings
ui_settings = UISettings()
