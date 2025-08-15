"""Authentication service for webhook handler"""
from fastapi import HTTPException, Header
from typing import Optional
from config import settings
from utils.logger import log

async def get_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    """Validate API key for subscription endpoints"""
    if not settings.api_keys:
        # No API keys configured, allow access
        return "default"
    
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")
    
    if x_api_key not in settings.api_keys:
        log.warning(f"Invalid API key attempt: {x_api_key[:8]}...")
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    return x_api_key