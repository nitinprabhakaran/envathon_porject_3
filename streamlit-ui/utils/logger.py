"""Logger setup for Streamlit UI"""
import sys
from loguru import logger
import os

def setup_logger():
    """Configure logger for Streamlit"""
    logger.remove()
    
    # Console handler
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level=os.getenv("LOG_LEVEL", "INFO"),
        colorize=True
    )
    
    # File handler
    logger.add(
        "logs/streamlit.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
        level=os.getenv("LOG_LEVEL", "INFO"),
        rotation="100 MB",
        retention="7 days"
    )
    
    return logger