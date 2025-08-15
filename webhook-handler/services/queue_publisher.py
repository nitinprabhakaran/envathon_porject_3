"""Queue Publisher for webhook events"""
import json
import asyncio
from typing import Dict, Any
import aio_pika
import boto3
from utils.logger import log
from config import settings
from datetime import datetime

class QueuePublisher:
    """Publish events to message queue (RabbitMQ or SQS)"""
    
    def __init__(self):
        self.queue_type = settings.queue_type
        self.connection = None
        self.channel = None
        self.sqs_client = None
        
        if self.queue_type == "sqs":
            self.sqs_client = boto3.client('sqs', region_name=settings.aws_region)
    
    async def connect(self):
        """Connect to message queue"""
        if self.queue_type == "rabbitmq":
            try:
                self.connection = await aio_pika.connect_robust(settings.rabbitmq_url)
                self.channel = await self.connection.channel()
                
                # Declare exchange and queue
                exchange = await self.channel.declare_exchange(
                    "webhook_events",
                    aio_pika.ExchangeType.TOPIC,
                    durable=True
                )
                
                queue = await self.channel.declare_queue(
                    "webhook_processing",
                    durable=True
                )
                
                await queue.bind(exchange, routing_key="webhook.*")
                log.info("Connected to RabbitMQ")
                
            except Exception as e:
                log.error(f"Failed to connect to RabbitMQ: {e}")
                raise
    
    async def publish_event(
        self,
        event_type: str,
        session_id: str,
        data: Dict[str, Any]
    ) -> bool:
        """Publish event to queue"""
        try:
            message = {
                "event_type": event_type,
                "session_id": session_id,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            if self.queue_type == "rabbitmq":
                if not self.channel:
                    await self.connect()
                
                exchange = await self.channel.get_exchange("webhook_events")
                await exchange.publish(
                    aio_pika.Message(
                        body=json.dumps(message).encode(),
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT
                    ),
                    routing_key=f"webhook.{event_type}"
                )
                log.info(f"Published {event_type} event for session {session_id}")
                
            elif self.queue_type == "sqs":
                self.sqs_client.send_message(
                    QueueUrl=settings.sqs_queue_url,
                    MessageBody=json.dumps(message),
                    MessageAttributes={
                        'event_type': {'StringValue': event_type, 'DataType': 'String'},
                        'session_id': {'StringValue': session_id, 'DataType': 'String'}
                    }
                )
                log.info(f"Published {event_type} to SQS for session {session_id}")
            
            return True
            
        except Exception as e:
            log.error(f"Failed to publish event: {e}")
            return False
    
    async def health_check(self) -> bool:
        """Check queue connection health"""
        if self.queue_type == "rabbitmq":
            if not self.connection or self.connection.is_closed:
                await self.connect()
            return not self.connection.is_closed
        elif self.queue_type == "sqs":
            try:
                self.sqs_client.get_queue_attributes(
                    QueueUrl=settings.sqs_queue_url,
                    AttributeNames=['ApproximateNumberOfMessages']
                )
                return True
            except:
                return False
        return False
    
    async def close(self):
        """Close queue connection"""
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
            log.info("Closed RabbitMQ connection")