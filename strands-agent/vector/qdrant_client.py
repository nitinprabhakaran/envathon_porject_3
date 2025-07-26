from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from typing import List, Dict, Any, Optional
import os
from datetime import datetime
import hashlib
from anthropic import Anthropic

class QdrantManager:
    def __init__(self):
        self.client = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))
        self.anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.collections = {
            "error_patterns": "error_patterns",
            "project_codebase": "project_codebase_",
            "shared_templates": "shared_pipeline_templates",
            "error_to_code": "error_to_code_mappings",
            "cicd_context": "cicd_context"
        }
    
    async def init_collections(self):
        """Initialize vector collections"""
        # Error patterns collection
        await self._create_collection_if_not_exists(
            self.collections["error_patterns"],
            vector_size=1536,
            distance=Distance.COSINE
        )
        
        # Shared templates collection
        await self._create_collection_if_not_exists(
            self.collections["shared_templates"],
            vector_size=1536,
            distance=Distance.COSINE
        )
        
        # Error to code mappings
        await self._create_collection_if_not_exists(
            self.collections["error_to_code"],
            vector_size=1536,
            distance=Distance.COSINE
        )
        
        # CI/CD context collection
        await self._create_collection_if_not_exists(
            self.collections["cicd_context"],
            vector_size=1536,
            distance=Distance.COSINE
        )
    
    async def _create_collection_if_not_exists(
        self,
        collection_name: str,
        vector_size: int,
        distance: Distance
    ):
        """Create collection if it doesn't exist"""
        collections = await self.client.get_collections()
        if collection_name not in [c.name for c in collections.collections]:
            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=vector_size, distance=distance)
            )
    
    async def embed_text(self, text: str) -> List[float]:
        """Create embeddings using Anthropic"""
        # Note: This is a placeholder - Anthropic doesn't provide embeddings
        # In production, use OpenAI, Cohere, or another embedding service
        # For now, return a mock embedding
        import numpy as np
        return np.random.rand(1536).tolist()
    
    async def search_similar_errors(
        self,
        error_signature: str,
        project_id: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar errors in historical data"""
        embedding = await self.embed_text(error_signature)
        
        # Search in error patterns
        results = await self.client.search(
            collection_name=self.collections["error_patterns"],
            query_vector=embedding,
            limit=limit,
            query_filter={
                "must": [{"key": "project_id", "match": {"value": project_id}}]
            } if project_id else None
        )
        
        return [
            {
                "id": point.id,
                "score": point.score,
                "payload": point.payload
            }
            for point in results
        ]
    
    async def search_code_context(
        self,
        project_id: str,
        query: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for relevant code in project embeddings"""
        collection_name = f"{self.collections['project_codebase']}{project_id}"
        
        # Check if project collection exists
        collections = await self.client.get_collections()
        if collection_name not in [c.name for c in collections.collections]:
            return []
        
        embedding = await self.embed_text(query)
        
        results = await self.client.search(
            collection_name=collection_name,
            query_vector=embedding,
            limit=limit
        )
        
        return [
            {
                "file_path": point.payload.get("file_path"),
                "code_chunk": point.payload.get("code_chunk"),
                "score": point.score,
                "function_name": point.payload.get("function_name")
            }
            for point in results
        ]
    
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
        
        # Store in error patterns
        await self.client.upsert(
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
    
    async def embed_project_code(
        self,
        project_id: str,
        files: List[Dict[str, Any]],
        priority: str = "high"
    ):
        """Embed project code files into vector database"""
        collection_name = f"{self.collections['project_codebase']}{project_id}"
        
        # Create collection if needed
        await self._create_collection_if_not_exists(
            collection_name,
            vector_size=1536,
            distance=Distance.COSINE
        )
        
        points = []
        for file_data in files:
            # Create chunks at function level
            chunks = self._chunk_code(file_data["content"], file_data["file_path"])
            
            for chunk in chunks:
                embedding = await self.embed_text(chunk["content"])
                chunk_id = hashlib.sha256(
                    f"{project_id}{file_data['file_path']}{chunk['content'][:100]}".encode()
                ).hexdigest()[:16]
                
                points.append(
                    PointStruct(
                        id=chunk_id,
                        vector=embedding,
                        payload={
                            "file_path": file_data["file_path"],
                            "file_type": file_data.get("file_type", "source"),
                            "code_chunk": chunk["content"],
                            "function_name": chunk.get("function_name"),
                            "priority": priority,
                            "embedded_at": datetime.utcnow().isoformat()
                        }
                    )
                )
        
        # Batch upsert
        if points:
            await self.client.upsert(
                collection_name=collection_name,
                points=points
            )
    
    def _chunk_code(self, content: str, file_path: str) -> List[Dict[str, Any]]:
        """Chunk code at function level"""
        # Simplified chunking - in production use proper AST parsing
        chunks = []
        
        # Basic function detection for common languages
        if file_path.endswith(('.py', '.js', '.ts', '.go')):
            lines = content.split('\n')
            current_chunk = []
            current_function = None
            
            for line in lines:
                # Simple function detection
                if any(keyword in line for keyword in ['def ', 'function ', 'func ']):
                    if current_chunk:
                        chunks.append({
                            "content": '\n'.join(current_chunk),
                            "function_name": current_function
                        })
                    current_chunk = [line]
                    current_function = line.strip()
                else:
                    current_chunk.append(line)
            
            # Add last chunk
            if current_chunk:
                chunks.append({
                    "content": '\n'.join(current_chunk),
                    "function_name": current_function
                })
        else:
            # For other files, chunk by size
            chunk_size = 50  # lines
            lines = content.split('\n')
            for i in range(0, len(lines), chunk_size):
                chunks.append({
                    "content": '\n'.join(lines[i:i+chunk_size]),
                    "function_name": None
                })
        
        return chunks if chunks else [{"content": content, "function_name": None}]

async def init_vector_db():
    """Initialize vector database"""
    manager = QdrantManager()
    await manager.init_collections()