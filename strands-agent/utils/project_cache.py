from functools import lru_cache
import asyncio

class ProjectCache:
    def __init__(self):
        self._cache = {}
        self._lock = asyncio.Lock()
    
    async def get_or_fetch(self, project_name: str):
        """Get project ID from cache or fetch from GitLab"""
        if project_name in self._cache:
            return self._cache[project_name]
        
        async with self._lock:
            # Double-check after acquiring lock
            if project_name in self._cache:
                return self._cache[project_name]
            
            # Fetch from GitLab
            from tools.gitlab_tools import get_project_by_name
            project = await get_project_by_name(project_name)
            if project:
                self._cache[project_name] = project["id"]
                return project["id"]
            
            return None

# Singleton instance
project_cache = ProjectCache()