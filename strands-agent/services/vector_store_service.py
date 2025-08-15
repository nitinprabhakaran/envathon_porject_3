"""Abstracted Vector Store - Switches between local OpenSearch and AWS OpenSearch"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import hashlib
from sentence_transformers import SentenceTransformer
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
import boto3
from utils.logger import log
from config import settings

class VectorStoreService:
    """Vector store that switches between local and AWS OpenSearch"""
    
    def __init__(self):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.client = None
        self.index_name = settings.opensearch_index
        
    async def init(self):
        """Initialize OpenSearch connection based on deployment mode"""
        try:
            if settings.vector_store_type == "aws":
                # AWS OpenSearch with IAM authentication
                credentials = boto3.Session().get_credentials()
                awsauth = AWS4Auth(
                    credentials.access_key,
                    credentials.secret_key,
                    settings.aws_opensearch_region,
                    'es',
                    session_token=credentials.token
                )
                
                self.client = OpenSearch(
                    hosts=[{'host': settings.aws_opensearch_endpoint.replace('https://', ''), 'port': 443}],
                    http_auth=awsauth,
                    use_ssl=True,
                    verify_certs=True,
                    connection_class=RequestsHttpConnection,
                    timeout=30
                )
                log.info(f"Connected to AWS OpenSearch: {settings.aws_opensearch_endpoint}")
            else:
                # Local OpenSearch without authentication
                self.client = OpenSearch(
                    hosts=[settings.local_opensearch_endpoint],
                    http_auth=(settings.opensearch_username, settings.opensearch_password) 
                        if settings.opensearch_username else None,
                    use_ssl=False,
                    verify_certs=False,
                    timeout=30
                )
                log.info(f"Connected to local OpenSearch: {settings.local_opensearch_endpoint}")
            
            await self.create_index()
            
        except Exception as e:
            log.error(f"Failed to initialize vector store: {e}")
            self.client = None
    
    async def create_index(self):
        """Create index if not exists"""
        if not self.client:
            return
        
        index_body = {
            "settings": {
                "index": {
                    "number_of_shards": 2,
                    "number_of_replicas": 1,
                    "knn": True if settings.vector_store_type == "aws" else False
                }
            },
            "mappings": {
                "properties": {
                    "error_signature": {"type": "text"},
                    "error_signature_hash": {"type": "keyword"},
                    "fix_description": {"type": "text"},
                    "fix_embedding": {
                        "type": "knn_vector" if settings.vector_store_type == "aws" else "dense_vector",
                        "dimension": 384
                    },
                    "files_changed": {"type": "keyword"},
                    "fix_content": {"type": "object", "enabled": False},
                    "project_id": {"type": "keyword"},
                    "success_rate": {"type": "float"},
                    "created_at": {"type": "date"}
                }
            }
        }
        
        if not self.client.indices.exists(index=self.index_name):
            self.client.indices.create(index=self.index_name, body=index_body)
            log.info(f"Created index: {self.index_name}")
    
    async def store_successful_fix(
        self,
        session_data: Dict[str, Any],
        fix_attempt: Dict[str, Any],
        fix_files: Dict[str, str]
    ) -> bool:
        """Store successful fix - works with both local and AWS"""
        if not self.client:
            log.warning("Vector store not available")
            return False
        
        try:
            error_signature = self._generate_error_signature(session_data)
            error_hash = hashlib.sha256(error_signature.encode()).hexdigest()
            
            # Generate embedding
            text_to_embed = f"{error_signature} {fix_attempt.get('description', '')}"
            embedding = self.model.encode(text_to_embed).tolist()
            
            document = {
                "error_signature": error_signature,
                "error_signature_hash": error_hash,
                "fix_description": fix_attempt.get("description", ""),
                "fix_embedding": embedding,
                "files_changed": list(fix_files.keys()),
                "fix_content": fix_files,
                "project_id": session_data.get("project_id"),
                "success_rate": 1.0,
                "created_at": datetime.utcnow().isoformat()
            }
            
            self.client.index(
                index=self.index_name,
                body=document
            )
            
            log.info(f"Stored fix for {error_hash}")
            return True
            
        except Exception as e:
            log.error(f"Failed to store fix: {e}")
            return False
    
    async def search_similar_fixes(
        self,
        error_description: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar fixes - works with both backends"""
        if not self.client:
            return []
        
        try:
            query_embedding = self.model.encode(error_description).tolist()
            
            if settings.vector_store_type == "aws":
                # AWS OpenSearch with KNN
                query = {
                    "size": limit,
                    "query": {
                        "knn": {
                            "fix_embedding": {
                                "vector": query_embedding,
                                "k": limit
                            }
                        }
                    }
                }
            else:
                # Local OpenSearch with script score
                query = {
                    "size": limit,
                    "query": {
                        "script_score": {
                            "query": {"match_all": {}},
                            "script": {
                                "source": "cosineSimilarity(params.query_vector, 'fix_embedding') + 1.0",
                                "params": {"query_vector": query_embedding}
                            }
                        }
                    }
                }
            
            response = self.client.search(
                index=self.index_name,
                body=query
            )
            
            return [hit["_source"] for hit in response["hits"]["hits"]]
            
        except Exception as e:
            log.error(f"Search failed: {e}")
            return []
    
    def _generate_error_signature(self, session_data: Dict[str, Any]) -> str:
        """Generate error signature from session data"""
        components = []
        
        if session_data.get("failed_stage"):
            components.append(f"stage:{session_data['failed_stage']}")
        
        if session_data.get("job_name"):
            components.append(f"job:{session_data['job_name']}")
        
        return " ".join(components) or "unknown_error"