from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from typing import List, Dict, Any, Optional
import os
from datetime import datetime
import hashlib
import numpy as np
from loguru import logger

class QdrantManager:
    def __init__(self):
        self.client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
        self.collections = {
            "error_patterns": "error_patterns",
            "project_codebase": "project_codebase_",
            "shared_templates": "shared_pipeline_templates",
            "error_to_code": "error_to_code_mappings",
            "cicd_context": "cicd_context"
        }
    
    async def init_collections(self):
        """Initialize vector collections"""
        collections_config = [
            (self.collections["error_patterns"], 1536, Distance.COSINE),
            (self.collections["shared_templates"], 1536, Distance.COSINE),
            (self.collections["error_to_code"], 1536, Distance.COSINE),
            (self.collections["cicd_context"], 1536, Distance.COSINE)
        ]
        
        for collection_name, vector_size, distance in collections_config:
            await self._create_collection_if_not_exists(collection_name, vector_size, distance)
    
    async def _create_collection_if_not_exists(
        self,
        collection_name: str,
        vector_size: int,
        distance: Distance
    ):
        """Create collection if it doesn't exist"""
        try:
            collections = self.client.get_collections()
            if collection_name not in [c.name for c in collections.collections]:
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=distance)
                )
                logger.info(f"Created collection: {collection_name}")
        except Exception as e:
            logger.error(f"Failed to create collection {collection_name}: {e}")
    
    async def embed_text(self, text: str) -> List[float]:
        """Create embeddings - using mock for now"""
        # TODO: Integrate with OpenAI or other embedding service
        # For now, return consistent mock embeddings based on text hash
        text_hash = hashlib.md5(text.encode()).hexdigest()
        seed = int(text_hash[:8], 16)
        np.random.seed(seed)
        return np.random.rand(1536).tolist()
    
    async def search_similar_errors(
        self,
        error_signature: str,
        project_id: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar errors in historical data"""
        embedding = await self.embed_text(error_signature)
        
        try:
            results = self.client.search(
                collection_name=self.collections["error_patterns"],
                query_vector=embedding,
                limit=limit,
                query_filter={
                    "must": [{"key": "project_id", "match": {"value": project_id}}]
                } if project_id else None
            )
            
            return [
                {
                    "id": str(point.id),
                    "score": point.score,
                    "payload": point.payload or {}
                }
                for point in results
            ]
        except Exception as e:
            logger.error(f"Error searching similar errors: {e}")
            return []
    
    async def search_code_context(
        self,
        project_id: str,
        query: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for relevant code in project embeddings"""
        collection_name = f"{self.collections['project_codebase']}{project_id}"
        
        # Check if collection exists
        try:
            collections = self.client.get_collections()
            if collection_name not in [c.name for c in collections.collections]:
                return []
            
            embedding = await self.embed_text(query)
            
            results = self.client.search(
                collection_name=collection_name,
                query_vector=embedding,
                limit=limit
            )
            
            return [
                {
                    "file_path": point.payload.get("file_path", ""),
                    "code_chunk": point.payload.get("code_chunk", ""),
                    "score": point.score,
                    "function_name": point.payload.get("function_name")
                }
                for point in results
            ]
        except Exception as e:
            logger.error(f"Error searching code context: {e}")
            return []
    
    async def store_successful_fix(
        self,
        error_signature: str,
        fix_description: str,
        project_context: Dict[str, Any]
    ):
        """Store a successful fix in vector database"""
        embedding = await self.embed_text(error_signature + " " + fix_description)
        
        # Generate unique ID
        fix_id = hashlib.sha256(
            f"{error_signature}{fix_description}{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        try:
            self.client.upsert(
                collection_name=self.collections["error_patterns"],
                points=[
                    PointStruct(
                        id=fix_id,
                        vector=embedding,
                        payload={
                            "error_signature": error_signature,
                            "fix_description": fix_description,
                            "project_id": project_context.get("project_id"),
                            "fix_type": project_context.get("fix_type"),
                            "confidence": project_context.get("confidence", 0.8),
                            "created_at": datetime.utcnow().isoformat(),
                            "success_count": 1,
                            "failure_count": 0
                        }
                    )
                ]
            )
        except Exception as e:
            logger.error(f"Error storing successful fix: {e}")

async def init_vector_db():
    """Initialize vector database"""
    manager = QdrantManager()
    await manager.init_collections()