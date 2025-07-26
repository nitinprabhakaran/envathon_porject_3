import os
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
import json
import boto3
from anthropic import Anthropic
from loguru import logger

class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    @abstractmethod
    async def complete(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Generate completion from messages"""
        pass
    
    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Generate embeddings for text"""
        pass

class BedrockProvider(LLMProvider):
    """AWS Bedrock provider for Claude models"""
    
    def __init__(self):
        self.model_id = os.getenv("MODEL_ID", "anthropic.claude-v2")
        
        # Initialize Bedrock client with credentials
        self.client = boto3.client(
            'bedrock-runtime',
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=os.getenv("AWS_SESSION_TOKEN")  # Optional for temporary creds
        )
        
        # For embeddings, we'll use Bedrock's Titan embeddings
        self.embeddings_model = "amazon.titan-embed-text-v1"
    
    async def complete(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Generate completion using Bedrock Claude"""
        # Convert messages to Claude format
        prompt = self._format_messages_for_claude(messages)
        
        # Prepare request body
        request_body = {
            "prompt": prompt,
            "max_tokens_to_sample": kwargs.get("max_tokens", 4000),
            "temperature": kwargs.get("temperature", 0.7),
            "top_p": kwargs.get("top_p", 0.9),
            "stop_sequences": kwargs.get("stop_sequences", ["\n\nHuman:", "\n\nAssistant:"])
        }
        
        try:
            # Invoke Bedrock
            response = self.client.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(request_body)
            )
            
            # Parse response
            response_body = json.loads(response['body'].read())
            return response_body.get('completion', '').strip()
            
        except Exception as e:
            logger.error(f"Bedrock completion error: {e}")
            raise
    
    async def embed(self, text: str) -> List[float]:
        """Generate embeddings using Bedrock Titan"""
        try:
            response = self.client.invoke_model(
                modelId=self.embeddings_model,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({"inputText": text})
            )
            
            response_body = json.loads(response['body'].read())
            return response_body.get('embedding', [])
            
        except Exception as e:
            logger.error(f"Bedrock embedding error: {e}")
            # Return mock embedding as fallback
            import numpy as np
            return np.random.rand(1536).tolist()
    
    def _format_messages_for_claude(self, messages: List[Dict[str, str]]) -> str:
        """Format messages for Claude's expected format"""
        formatted = ""
        
        for msg in messages:
            if msg["role"] == "system":
                formatted += f"\n\n{msg['content']}\n\n"
            elif msg["role"] == "user":
                formatted += f"\n\nHuman: {msg['content']}"
            elif msg["role"] == "assistant":
                formatted += f"\n\nAssistant: {msg['content']}"
        
        # Always end with Assistant: for Claude to continue
        if not formatted.endswith("\n\nAssistant:"):
            formatted += "\n\nAssistant:"
        
        return formatted

class AnthropicProvider(LLMProvider):
    """Anthropic SDK provider"""
    
    def __init__(self):
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = os.getenv("MODEL_ID", "claude-3-opus-20240229")
    
    async def complete(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Generate completion using Anthropic SDK"""
        # Separate system message
        system_message = None
        conversation_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                conversation_messages.append(msg)
        
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=kwargs.get("max_tokens", 4000),
                temperature=kwargs.get("temperature", 0.7),
                system=system_message,
                messages=conversation_messages
            )
            
            return response.content[0].text
            
        except Exception as e:
            logger.error(f"Anthropic completion error: {e}")
            raise
    
    async def embed(self, text: str) -> List[float]:
        """Generate embeddings - Anthropic doesn't provide embeddings"""
        # Use a third-party service or return mock embeddings
        logger.warning("Anthropic doesn't provide embeddings, using mock embeddings")
        import numpy as np
        return np.random.rand(1536).tolist()

class LLMFactory:
    """Factory for creating LLM providers"""
    
    @staticmethod
    def create_provider() -> LLMProvider:
        """Create LLM provider based on configuration"""
        provider_type = os.getenv("LLM_PROVIDER", "bedrock").lower()
        
        if provider_type == "bedrock":
            logger.info("Using AWS Bedrock provider")
            return BedrockProvider()
        elif provider_type == "anthropic":
            logger.info("Using Anthropic SDK provider")
            return AnthropicProvider()
        else:
            raise ValueError(f"Unknown LLM provider: {provider_type}")

# Global provider instance
llm_provider = LLMFactory.create_provider()