"""Abstracted Queue Service - Switches between RabbitMQ/Redis/SQS based on config"""
import json
import boto3
import aio_pika
import redis.asyncio as redis
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod
from utils.logger import log
from config import settings

class QueueBackend(ABC):
    """Abstract base for queue backends"""
    
    @abstractmethod
    async def connect(self):
        pass
    
    @abstractmethod
    async def publish(self, message: Dict[str, Any]):
        pass
    
    @abstractmethod
    async def consume(self, callback):
        pass
    
    @abstractmethod
    async def close(self):
        pass

class RabbitMQBackend(QueueBackend):
    """RabbitMQ implementation"""
    
    def __init__(self):
        self.connection = None
        self.channel = None
        
    async def connect(self):
        self.connection = await aio_pika.connect_robust(settings.rabbitmq_url)
        self.channel = await self.connection.channel()
        await self.channel.declare_queue(settings.queue_name, durable=True)
        log.info("Connected to RabbitMQ")
    
    async def publish(self, message: Dict[str, Any]):
        if not self.channel:
            await self.connect()
        
        await self.channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(message).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key=settings.queue_name
        )
    
    async def consume(self, callback):
        if not self.channel:
            await self.connect()
        
        queue = await self.channel.declare_queue(settings.queue_name, durable=True)
        await self.channel.set_qos(prefetch_count=10)
        
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    await callback(json.loads(message.body))
    
    async def close(self):
        if self.connection:
            await self.connection.close()

class RedisBackend(QueueBackend):
    """Redis List implementation"""
    
    def __init__(self):
        self.client = None
        
    async def connect(self):
        self.client = await redis.from_url(settings.redis_url)
        log.info("Connected to Redis")
    
    async def publish(self, message: Dict[str, Any]):
        if not self.client:
            await self.connect()
        
        await self.client.rpush(settings.queue_name, json.dumps(message))
    
    async def consume(self, callback):
        if not self.client:
            await self.connect()
        
        while True:
            message = await self.client.blpop(settings.queue_name, timeout=30)
            if message:
                _, data = message
                await callback(json.loads(data))
    
    async def close(self):
        if self.client:
            await self.client.close()

class SQSBackend(QueueBackend):
    """AWS SQS implementation"""
    
    def __init__(self):
        self.client = boto3.client(
            'sqs',
            region_name=settings.sqs_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            aws_session_token=settings.aws_session_token
        )
        self.queue_url = settings.sqs_queue_url
        
    async def connect(self):
        log.info(f"Connected to SQS: {self.queue_url}")
    
    async def publish(self, message: Dict[str, Any]):
        self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(message)
        )
    
    async def consume(self, callback):
        while True:
            response = self.client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=20
            )
            
            for message in response.get('Messages', []):
                await callback(json.loads(message['Body']))
                
                # Delete after processing
                self.client.delete_message(
                    QueueUrl=self.queue_url,
                    ReceiptHandle=message['ReceiptHandle']
                )
    
    async def close(self):
        pass

class QueueService:
    """Unified queue service that switches backends based on config"""
    
    def __init__(self):
        self.backend: Optional[QueueBackend] = None
        self._initialize_backend()
    
    def _initialize_backend(self):
        """Initialize the appropriate backend based on settings"""
        if settings.queue_type == "sqs":
            self.backend = SQSBackend()
            log.info("Using SQS backend")
        elif settings.queue_type == "redis":
            self.backend = RedisBackend()
            log.info("Using Redis backend")
        else:
            self.backend = RabbitMQBackend()
            log.info("Using RabbitMQ backend")
    
    async def connect(self):
        await self.backend.connect()
    
    async def publish(self, message: Dict[str, Any]):
        await self.backend.publish(message)
    
    async def consume(self, callback):
        await self.backend.consume(callback)
    
    async def close(self):
        await self.backend.close()