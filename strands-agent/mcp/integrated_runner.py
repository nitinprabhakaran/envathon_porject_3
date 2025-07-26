import asyncio
import subprocess
import os
import json
from typing import Dict, Any, Optional
import aiofiles
from loguru import logger

class MCPManager:
    def __init__(self):
        self.gitlab_process = None
        self.sonar_process = None
        self.gitlab_healthy = False
        self.sonar_healthy = False
        
    async def start(self):
        """Start MCP servers as subprocesses"""
        try:
            # Start GitLab MCP
            logger.info("Starting GitLab MCP server...")
            self.gitlab_process = await self._start_gitlab_mcp()
            self.gitlab_healthy = await self._check_gitlab_health()
            
            # Start SonarQube MCP
            logger.info("Starting SonarQube MCP server...")
            self.sonar_process = await self._start_sonar_mcp()
            self.sonar_healthy = await self._check_sonar_health()
            
        except Exception as e:
            logger.error(f"Failed to start MCP servers: {e}")
            await self.stop()
            raise
    
    async def _start_gitlab_mcp(self):
        """Start GitLab MCP server subprocess"""
        env = os.environ.copy()
        env.update({
            "GITLAB_URL": os.getenv("GITLAB_URL"),
            "GITLAB_TOKEN": os.getenv("GITLAB_TOKEN")
        })
        
        process = await asyncio.create_subprocess_exec(
            "node", "/mcp/gitlab-mcp/index.js",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
        
        return process
    
    async def _start_sonar_mcp(self):
        """Start SonarQube MCP server subprocess"""
        env = os.environ.copy()
        env.update({
            "SONAR_HOST_URL": os.getenv("SONAR_HOST_URL"),
            "SONAR_TOKEN": os.getenv("SONAR_TOKEN")
        })
        
        process = await asyncio.create_subprocess_exec(
            "python", "/mcp/sonarqube-mcp/server.py",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )
        
        return process
    
    async def _check_gitlab_health(self) -> bool:
        """Check if GitLab MCP is healthy"""
        try:
            result = await self.gitlab_call("list_tools", {})
            return "tools" in result
        except:
            return False
    
    async def _check_sonar_health(self) -> bool:
        """Check if SonarQube MCP is healthy"""
        try:
            result = await self.sonar_call("list_tools", {})
            return "tools" in result
        except:
            return False
    
    async def gitlab_call(self, method: str, params: Dict[str, Any]) -> Any:
        """Call GitLab MCP server via STDIO"""
        if not self.gitlab_process:
            raise RuntimeError("GitLab MCP server not started")
        
        # Create JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        
        # Send request
        request_str = json.dumps(request) + "\n"
        self.gitlab_process.stdin.write(request_str.encode())
        await self.gitlab_process.stdin.drain()
        
        # Read response
        response_line = await self.gitlab_process.stdout.readline()
        response = json.loads(response_line.decode())
        
        if "error" in response:
            raise Exception(f"GitLab MCP error: {response['error']}")
        
        return response.get("result")
    
    async def sonar_call(self, method: str, params: Dict[str, Any]) -> Any:
        """Call SonarQube MCP server via STDIO"""
        if not self.sonar_process:
            raise RuntimeError("SonarQube MCP server not started")
        
        # Create JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        
        # Send request
        request_str = json.dumps(request) + "\n"
        self.sonar_process.stdin.write(request_str.encode())
        await self.sonar_process.stdin.drain()
        
        # Read response
        response_line = await self.sonar_process.stdout.readline()
        response = json.loads(response_line.decode())
        
        if "error" in response:
            raise Exception(f"SonarQube MCP error: {response['error']}")
        
        return response.get("result")
    
    async def stop(self):
        """Stop MCP servers"""
        if self.gitlab_process:
            self.gitlab_process.terminate()
            await self.gitlab_process.wait()
        
        if self.sonar_process:
            self.sonar_process.terminate()
            await self.sonar_process.wait()