"""Vector Store Service for Strands Agent using AWS OpenSearch"""
import json
import hashlib
from typing import Dict, Any, List, Optional
from datetime import datetime
import numpy as np
from sentence_transformers import SentenceTransformer
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
import boto3
from utils.logger import log
from config import settings

class VectorStore:
    """Vector store for successful fixes - managed by Strands Agent"""
    
    def __init__(self):
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.client = None
        self.index_name = settings.opensearch_index
        
    async def init(self):
        """Initialize OpenSearch connection"""
        try:
            # AWS authentication
            credentials = boto3.Session().get_credentials()
            awsauth = AWS4Auth(
                credentials.access_key,
                credentials.secret_key,
                settings.aws_region,
                'es',
                session_token=credentials.token
            )
            
            # Create OpenSearch client
            self.client = OpenSearch(
                hosts=[{'host': settings.opensearch_endpoint.replace('https://', ''), 'port': 443}],
                http_auth=awsauth if not settings.opensearch_username else 
                          (settings.opensearch_username, settings.opensearch_password),
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
                timeout=30
            )
            
            # Create index if not exists
            await self.create_index()
            
            log.info("Vector store initialized with AWS OpenSearch")
            
        except Exception as e:
            log.error(f"Failed to initialize vector store: {e}")
            # Continue without vector store if it fails
            self.client = None
    
    async def create_index(self):
        """Create OpenSearch index with vector mapping"""
        if not self.client:
            return
            
        index_body = {
            "settings": {
                "index": {
                    "number_of_shards": 2,
                    "number_of_replicas": 1,
                    "knn": True
                }
            },
            "mappings": {
                "properties": {
                    # Error identification
                    "error_signature": {"type": "text"},
                    "error_signature_hash": {"type": "keyword"},
                    "error_type": {"type": "keyword"},  # pipeline, quality
                    "failed_stage": {"type": "keyword"},
                    "job_name": {"type": "keyword"},
                    
                    # Fix details
                    "fix_description": {"type": "text"},
                    "fix_embedding": {
                        "type": "knn_vector",
                        "dimension": 384,
                        "method": {
                            "name": "hnsw",
                            "space_type": "l2",
                            "engine": "faiss"
                        }
                    },
                    "files_changed": {"type": "keyword"},
                    "fix_content": {"type": "object", "enabled": False},  # Store as JSON
                    
                    # Project metadata
                    "project_id": {"type": "keyword"},
                    "project_name": {"type": "keyword"},
                    "project_type": {"type": "keyword"},
                    "language": {"type": "keyword"},
                    "branch": {"type": "keyword"},
                    
                    # Success metrics
                    "success_rate": {"type": "float"},
                    "application_count": {"type": "integer"},
                    "confidence_score": {"type": "float"},
                    
                    # Tracking
                    "session_id": {"type": "keyword"},
                    "merge_request_url": {"type": "keyword"},
                    "created_at": {"type": "date"},
                    "last_applied": {"type": "date"},
                    "applied_sessions": {"type": "keyword"},
                    
                    # Tags for categorization
                    "tags": {"type": "keyword"}
                }
            }
        }
        
        if not self.client.indices.exists(index=self.index_name):
            self.client.indices.create(index=self.index_name, body=index_body)
            log.info(f"Created OpenSearch index: {self.index_name}")
    
    async def store_successful_fix(
        self,
        session_data: Dict[str, Any],
        fix_attempt: Dict[str, Any],
        fix_files: Dict[str, str]
    ) -> bool:
        """Store a successful fix in vector database"""
        if not self.client:
            log.warning("Vector store not available, skipping fix storage")
            return False
            
        try:
            # Generate error signature
            error_signature = self._generate_error_signature(session_data)
            error_hash = hashlib.sha256(error_signature.encode()).hexdigest()
            
            # Generate embedding
            text_to_embed = f"{error_signature} {fix_attempt.get('description', '')}"
            embedding = self.model.encode(text_to_embed).tolist()
            
            # Check if similar fix exists
            existing = await self.find_exact_fix(error_hash)
            
            if existing:
                # Update existing fix
                await self._update_existing_fix(existing[0], session_data, fix_attempt)
                log.info(f"Updated existing fix for {error_hash}")
            else:
                # Create new fix entry
                document = {
                    "error_signature": error_signature,
                    "error_signature_hash": error_hash,
                    "error_type": session_data.get("session_type"),
                    "failed_stage": session_data.get("failed_stage"),
                    "job_name": session_data.get("job_name"),
                    
                    "fix_description": fix_attempt.get("description", ""),
                    "fix_embedding": embedding,
                    "files_changed": list(fix_files.keys()),
                    "fix_content": fix_files,  # Store actual file contents
                    
                    "project_id": session_data.get("project_id"),
                    "project_name": session_data.get("project_name"),
                    "project_type": self._detect_project_type(session_data),
                    "language": self._detect_language(fix_files),
                    "branch": session_data.get("branch"),
                    
                    "success_rate": 1.0,
                    "application_count": 1,
                    "confidence_score": 0.9,
                    
                    "session_id": session_data.get("session_id"),
                    "merge_request_url": fix_attempt.get("merge_request_url"),
                    "created_at": datetime.utcnow().isoformat(),
                    "last_applied": datetime.utcnow().isoformat(),
                    "applied_sessions": [session_data.get("session_id")],
                    
                    "tags": self._generate_tags(session_data, fix_files)
                }
                
                self.client.index(
                    index=self.index_name,
                    body=document
                )
                
                log.info(f"Stored new fix for {error_hash}")
            
            return True
            
        except Exception as e:
            log.error(f"Failed to store fix: {e}")
            return False
    
    async def search_similar_fixes(
        self,
        error_description: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar fixes using vector similarity"""
        if not self.client:
            return []
            
        try:
            # Generate embedding for search
            query_embedding = self.model.encode(error_description).tolist()
            
            # Build query
            query_body = {
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
            
            # Add filters
            if filters:
                filter_conditions = []
                
                if "project_type" in filters:
                    filter_conditions.append({"term": {"project_type": filters["project_type"]}})
                
                if "language" in filters:
                    filter_conditions.append({"term": {"language": filters["language"]}})
                
                if "error_type" in filters:
                    filter_conditions.append({"term": {"error_type": filters["error_type"]}})
                
                if filter_conditions:
                    query_body["query"] = {
                        "bool": {
                            "must": [query_body["query"]],
                            "filter": filter_conditions
                        }
                    }
            
            response = self.client.search(
                index=self.index_name,
                body=query_body
            )
            
            results = []
            for hit in response["hits"]["hits"]:
                result = hit["_source"]
                result["similarity_score"] = hit["_score"]
                results.append(result)
            
            return results
            
        except Exception as e:
            log.error(f"Failed to search similar fixes: {e}")
            return []
    
    async def find_exact_fix(self, error_hash: str) -> List[Dict[str, Any]]:
        """Find exact fix by error signature hash"""
        if not self.client:
            return []
            
        try:
            query = {
                "query": {
                    "term": {
                        "error_signature_hash": error_hash
                    }
                },
                "size": 1
            }
            
            response = self.client.search(
                index=self.index_name,
                body=query
            )
            
            return response["hits"]["hits"]
            
        except Exception as e:
            log.error(f"Failed to find exact fix: {e}")
            return []
    
    async def get_successful_fix_by_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get successful fix details by session ID"""
        if not self.client:
            return None
            
        try:
            query = {
                "query": {
                    "term": {
                        "session_id": session_id
                    }
                },
                "size": 1
            }
            
            response = self.client.search(
                index=self.index_name,
                body=query
            )
            
            hits = response["hits"]["hits"]
            if hits:
                return hits[0]["_source"]
            return None
            
        except Exception as e:
            log.error(f"Failed to get fix by session: {e}")
            return None
    
    def _generate_error_signature(self, session_data: Dict[str, Any]) -> str:
        """Generate error signature from session data"""
        if session_data.get("error_signature"):
            return session_data["error_signature"]
        
        # Build signature from available data
        components = []
        
        if session_data.get("failed_stage"):
            components.append(f"stage:{session_data['failed_stage']}")
        
        if session_data.get("job_name"):
            components.append(f"job:{session_data['job_name']}")
        
        if session_data.get("error_type"):
            components.append(f"type:{session_data['error_type']}")
        
        # Add quality gate info if available
        if session_data.get("quality_gate_status"):
            components.append(f"quality:{session_data['quality_gate_status']}")
        
        return " ".join(components) or "unknown_error"
    
    def _detect_project_type(self, session_data: Dict[str, Any]) -> str:
        """Detect project type from session data"""
        project_name = session_data.get("project_name", "").lower()
        
        if "api" in project_name:
            return "api"
        elif "frontend" in project_name or "ui" in project_name:
            return "frontend"
        elif "service" in project_name:
            return "service"
        elif "lib" in project_name or "library" in project_name:
            return "library"
        else:
            return "application"
    
    def _detect_language(self, fix_files: Dict[str, str]) -> str:
        """Detect primary language from fixed files"""
        extensions = []
        for filepath in fix_files.keys():
            if "." in filepath:
                ext = filepath.split(".")[-1].lower()
                extensions.append(ext)
        
        # Map extensions to languages
        if "py" in extensions:
            return "python"
        elif "java" in extensions:
            return "java"
        elif any(ext in extensions for ext in ["js", "jsx", "ts", "tsx"]):
            return "javascript"
        elif "go" in extensions:
            return "go"
        elif any(ext in extensions for ext in ["yml", "yaml"]):
            return "yaml"
        else:
            return "unknown"
    
    def _generate_tags(self, session_data: Dict[str, Any], fix_files: Dict[str, str]) -> List[str]:
        """Generate tags for categorization"""
        tags = []
        
        # Add session type
        if session_data.get("session_type"):
            tags.append(session_data["session_type"])
        
        # Add language
        lang = self._detect_language(fix_files)
        if lang != "unknown":
            tags.append(lang)
        
        # Add stage
        if session_data.get("failed_stage"):
            tags.append(session_data["failed_stage"])
        
        # Add special tags
        if "dockerfile" in [f.lower() for f in fix_files.keys()]:
            tags.append("docker")
        
        if any("test" in f.lower() for f in fix_files.keys()):
            tags.append("testing")
        
        return tags
    
    async def _update_existing_fix(
        self,
        existing_doc: Dict[str, Any],
        session_data: Dict[str, Any],
        fix_attempt: Dict[str, Any]
    ):
        """Update an existing fix with new application"""
        if not self.client:
            return
            
        doc_id = existing_doc["_id"]
        doc = existing_doc["_source"]
        
        # Update metrics
        doc["application_count"] += 1
        doc["last_applied"] = datetime.utcnow().isoformat()
        doc["applied_sessions"].append(session_data.get("session_id"))
        
        # Update success rate (weighted average)
        doc["success_rate"] = min(1.0, doc["success_rate"] * 0.9 + 0.1)
        
        # Update MR URLs
        if fix_attempt.get("merge_request_url"):
            if "merge_request_urls" not in doc:
                doc["merge_request_urls"] = []
            doc["merge_request_urls"].append(fix_attempt["merge_request_url"])
        
        self.client.update(
            index=self.index_name,
            id=doc_id,
            body={"doc": doc}
        )