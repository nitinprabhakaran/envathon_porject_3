"""Unified Queue Processor using abstracted services"""
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from utils.logger import log
from config import settings
from agents.pipeline_agent import PipelineAgent
from agents.quality_agent import QualityAgent
from db.session_manager import SessionManager
from services.queue_service import QueueService
from services.vector_store_service import VectorStoreService

class UnifiedQueueProcessor:
    """Queue processor that works with any backend"""
    
    def __init__(self):
        self.queue_service = QueueService()
        self.vector_store = VectorStoreService()
        self.session_manager = SessionManager()
        self.pipeline_agent = PipelineAgent()
        self.quality_agent = QualityAgent()
        self.processing = False
        
    async def start(self):
        """Start processing queue messages"""
        self.processing = True
        log.info(f"Starting unified queue processor with {settings.queue_type}")
        
        # Initialize services
        await self.session_manager.init_pool()
        await self.vector_store.init()
        await self.queue_service.connect()
        
        # Start consuming
        try:
            await self.queue_service.consume(self.process_message)
        except Exception as e:
            log.error(f"Queue processing error: {e}")
            if self.processing:
                await asyncio.sleep(5)
                await self.start()  # Restart
    
    async def process_message(self, message: Dict[str, Any]):
        """Process a single message from any queue backend"""
        try:
            event_type = message.get('event_type')
            session_id = message.get('session_id')
            
            log.info(f"Processing {event_type} event for session {session_id}")
            
            if event_type == 'gitlab_pipeline':
                await self.process_gitlab_pipeline(message)
            elif event_type == 'sonarqube_quality':
                await self.process_sonarqube_quality(message)
                
        except Exception as e:
            log.error(f"Failed to process message: {e}", exc_info=True)
    
    # All the analysis functions remain the same...
    # (Include all the functions from the previous queue_processor.py)
    
    async def stop(self):
        """Stop processing"""
        self.processing = False
        await self.queue_service.close()
        log.info("Queue processor stopped")