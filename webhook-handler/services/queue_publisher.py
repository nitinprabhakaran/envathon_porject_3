"""Queue Publisher for local development"""
import json
import asyncio
import aio_pika
import redis.asyncio as redis
from typing import Dict, Any
from utils.logger import log
from config import settings

class QueuePublisher:
    """Publish events to RabbitMQ or Redis"""
    
    def __init__(self):
        self.queue_type = settings.queue_type  # 'rabbitmq' or 'redis'
        self.connection = None
        self.channel = None
        self.redis_client = None
        
    async def connect(self):
        """Connect to queue service"""
        if self.queue_type == 'rabbitmq':
            await self.connect_rabbitmq()
        else:
            await self.connect_redis()
    
    async def connect_rabbitmq(self):
        """Connect to RabbitMQ"""
        if not self.connection:
            self.connection = await aio_pika.connect_robust(
                settings.rabbitmq_url
            )
            self.channel = await self.connection.channel()
            
            # Declare queue
            await self.channel.declare_queue(
                settings.queue_name,
                durable=True
            )
            log.info("Connected to RabbitMQ")
    
    async def connect_redis(self):
        """Connect to Redis"""
        if not self.redis_client:
            self.redis_client = await redis.from_url(
                settings.redis_url,
                decode_responses=False
            )
            log.info("Connected to Redis")
    
    async def publish(self, message: Dict[str, Any]):
        """Publish message to queue"""
        await self.connect()
        
        message_json = json.dumps(message)
        
        if self.queue_type == 'rabbitmq':
            await self.publish_rabbitmq(message_json)
        else:
            await self.publish_redis(message_json)
    
    async def publish_rabbitmq(self, message: str):
        """Publish to RabbitMQ"""
        await self.channel.default_exchange.publish(
            aio_pika.Message(
                body=message.encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key=settings.queue_name
        )
        log.debug(f"Published message to RabbitMQ queue {settings.queue_name}")
    
    async def publish_redis(self, message: str):
        """Publish to Redis list"""
        await self.redis_client.rpush(settings.queue_name, message)
        log.debug(f"Published message to Redis list {settings.queue_name}")
    
    async def close(self):
        """Close connections"""
        if self.connection:
            await self.connection.close()
        if self.redis_client:
            await self.redis_client.close()