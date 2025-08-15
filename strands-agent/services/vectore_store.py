"""Vector Store Service for storing and retrieving fixes"""
from typing import Dict, Any, List, Optional
import json
import numpy as np
from datetime import datetime
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
import boto3
from sentence_transformers import SentenceTransformer
from utils.logger import log
from config import settings

class VectorStore:
    """OpenSearch-based vector store for CI/CD fixes"""
    
    def __init__(self):
        self.client = None
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        self.index_name = settings.vector_index_name
    
    async def init(self):
        """Initialize OpenSearch client and index"""
        try:
            # Check if using AWS OpenSearch
            if settings.opensearch_host.endswith('.amazonaws.com'):
                credentials = boto3.Session().get_credentials()
                awsauth = AWS4Auth(
                    credentials.access_key,
                    credentials.secret_key,
                    settings.aws_region,
                    'es',
                    session_token=credentials.token
                )
                
                self.client = OpenSearch(
                    hosts=[{'host': settings.opensearch_host, 'port': settings.opensearch_port}],
                    http_auth=awsauth,
                    use_ssl=True,
                    verify_certs=True,
                    connection_class=RequestsHttpConnection
                )
            else:
                # Local OpenSearch
                self.client = OpenSearch(
                    hosts=[{'host': settings.opensearch_host, 'port': settings.opensearch_port}],
                    http_auth=(settings.opensearch_user, settings.opensearch_password),
                    use_ssl=settings.opensearch_use_ssl,
                    verify_certs=False
                )
            
            # Create index if not exists
            await self._create_index()
            log.info("Vector store initialized")
            
        except Exception as e:
            log.error(f"Failed to initialize vector store: {e}")
            raise
    
    async def _create_index(self):
        """Create OpenSearch index with vector mapping"""
        if not self.client.indices.exists(index=self.index_name):
            mapping = {
                "settings": {
                    "index": {
                        "knn": True,
                        "knn.algo_param.ef_search": 100
                    }
                },
                "mappings": {
                    "properties": {
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": settings.vector_dimension,
                            "method": {
                                "name": "hnsw",
                                "space_type": "l2",
                                "engine": "nmslib",
                                "parameters": {
                                    "ef_construction": 128,
                                    "m": 24
                                }
                            }
                        },
                        "session_id": {"type": "keyword"},
                        "project_id": {"type": "keyword"},
                        "analysis_type": {"type": "keyword"},
                        "error_signature": {"type": "text"},
                        "solution": {"type": "text"},
                        "files_changed": {"type": "keyword"},
                        "success": {"type": "boolean"},
                        "created_at": {"type": "date"},
                        "metadata": {"type": "object"}
                    }
                }
            }
            
            self.client.indices.create(index=self.index_name, body=mapping)
            log.info(f"Created index: {self.index_name}")
    
    async def store_analysis(
        self,
        session_id: str,
        project_id: str,
        analysis_type: str,
        error_signature: str,
        solution: str,
        metadata: Dict[str, Any] = None
    ):
        """Store analysis result with vector embedding"""
        try:
            # Generate embedding
            text = f"{error_signature} {solution}"
            embedding = self.encoder.encode(text).tolist()
            
            # Prepare document
            doc = {
                "embedding": embedding,
                "session_id": session_id,
                "project_id": project_id,
                "analysis_type": analysis_type,
                "error_signature": error_signature,
                "solution": solution,
                "success": False,
                "created_at": datetime.utcnow(),
                "metadata": metadata or {}
            }
            
            # Index document
            self.client.index(
                index=self.index_name,
                body=doc,
                id=session_id
            )
            
            log.info(f"Stored analysis for session {session_id}")
            
        except Exception as e:
            log.error(f"Failed to store analysis: {e}")
    
    async def store_successful_fix(
        self,
        session_id: str,
        project_id: str,
        fix_type: str,
        problem_description: str,
        solution: str,
        files_changed: List[str],
        metadata: Dict[str, Any] = None
    ):
        """Store successful fix for future reference"""
        try:
            # Generate embedding
            text = f"{problem_description} {solution}"
            embedding = self.encoder.encode(text).tolist()
            
            # Prepare document
            doc = {
                "embedding": embedding,
                "session_id": session_id,
                "project_id": project_id,
                "analysis_type": fix_type,
                "error_signature": problem_description,
                "solution": solution,
                "files_changed": files_changed,
                "success": True,
                "created_at": datetime.utcnow(),
                "metadata": metadata or {}
            }
            
            # Update or create document
            self.client.index(
                index=self.index_name,
                body=doc,
                id=f"{session_id}_success"
            )
            
            log.info(f"Stored successful fix for session {session_id}")
            
        except Exception as e:
            log.error(f"Failed to store successful fix: {e}")
    
    async def search_similar_fixes(
        self,
        query: str,
        project_id: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar fixes using vector similarity"""
        try:
            # Generate query embedding
            query_embedding = self.encoder.encode(query).tolist()
            
            # Build search query
            search_query = {
                "size": limit,
                "query": {
                    "bool": {
                        "must": [
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": query_embedding,
                                        "k": limit
                                    }
                                }
                            }
                        ],
                        "filter": []
                    }
                }
            }
            
            # Add project filter if specified
            if project_id:
                search_query["query"]["bool"]["filter"].append({
                    "term": {"project_id": project_id}
                })
            
            # Only return successful fixes
            search_query["query"]["bool"]["filter"].append({
                "term": {"success": True}
            })
            
            # Execute search
            response = self.client.search(
                index=self.index_name,
                body=search_query
            )
            
            # Extract results
            results = []
            for hit in response['hits']['hits']:
                source = hit['_source']
                results.append({
                    "session_id": source.get("session_id"),
                    "project_id": source.get("project_id"),
                    "error_signature": source.get("error_signature"),
                    "solution": source.get("solution"),
                    "files_changed": source.get("files_changed", []),
                    "score": hit['_score'],
                    "created_at": source.get("created_at")
                })
            
            return results
            
        except Exception as e:
            log.error(f"Failed to search similar fixes: {e}")
            return []
    
    async def get_project_stats(self, project_id: str) -> Dict[str, Any]:
        """Get statistics for a project"""
        try:
            # Count successful fixes
            success_count = self.client.count(
                index=self.index_name,
                body={
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"project_id": project_id}},
                                {"term": {"success": True}}
                            ]
                        }
                    }
                }
            )
            
            # Count failed analyses
            failed_count = self.client.count(
                index=self.index_name,
                body={
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"project_id": project_id}},
                                {"term": {"success": False}}
                            ]
                        }
                    }
                }
            )
            
            return {
                "successful_fixes": success_count['count'],
                "failed_analyses": failed_count['count'],
                "total": success_count['count'] + failed_count['count']
            }
            
        except Exception as e:
            log.error(f"Failed to get project stats: {e}")
            return {"successful_fixes": 0, "failed_analyses": 0, "total": 0}
    
    async def health_check(self) -> bool:
        """Check OpenSearch health"""
        try:
            health = self.client.cluster.health()
            return health['status'] in ['green', 'yellow']
        except:
            return False