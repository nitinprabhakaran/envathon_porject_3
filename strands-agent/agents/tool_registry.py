"""Dynamic tool registry for agents - completely dynamic, no hardcoding"""
from typing import List, Dict, Any, Callable
from abc import ABC, abstractmethod
import importlib
import inspect
from pathlib import Path
import os


def extract_tool_description(tool: Callable) -> str:
    """Extract description from a tool function - shared utility"""
    if hasattr(tool, '__doc__') and tool.__doc__:
        # Extract first line of docstring as description
        doc_lines = tool.__doc__.strip().split('\n')
        return doc_lines[0].strip() if doc_lines else f"{tool.__name__} functionality"
    else:
        # Fallback to function name with some formatting
        name = tool.__name__ if hasattr(tool, '__name__') else str(tool)
        return name.replace('_', ' ').title() + " functionality"


def discover_tools_in_module(module_name: str) -> List[Callable]:
    """Dynamically discover all tools in a module using Strands SDK patterns"""
    tools = []
    try:
        module = importlib.import_module(module_name)
        
        # Use the same pattern as Strands SDK _scan_module_for_tools
        for name, obj in inspect.getmembers(module):
            # Check if it's a DecoratedFunctionTool (the type created by @tool decorator)
            try:
                # Import DecoratedFunctionTool to check isinstance
                from strands.tools.decorator import DecoratedFunctionTool
                
                if isinstance(obj, DecoratedFunctionTool):
                    # According to Strands documentation, we should pass the DecoratedFunctionTool objects directly
                    # The Agent constructor can handle them properly
                    tools.append(obj)
                    print(f"Found Strands tool: {name} -> {obj} (DecoratedFunctionTool)")
                    
            except ImportError:
                # Strands SDK not available, fall back to attribute checking
                if (hasattr(obj, 'tool_spec') and 
                    hasattr(obj, 'tool_name') and 
                    hasattr(obj, 'stream') and
                    callable(obj)):
                    tools.append(obj)
                    print(f"Found tool-like object: {name} -> {obj}")
                
    except ImportError as e:
        # Module not available - that's OK, just skip it
        print(f"Module {module_name} not available: {e}")
    except Exception as e:
        # Log error but don't fail
        print(f"Warning: Error discovering tools in {module_name}: {e}")
    
    print(f"Discovered {len(tools)} tools in {module_name}: {[tool.tool_name if hasattr(tool, 'tool_name') else str(tool) for tool in tools]}")
    return tools


def get_available_tool_modules() -> Dict[str, List[str]]:
    """Discover available tool modules dynamically"""
    tool_modules = {}
    
    # Check tools directory
    tools_dir = Path(__file__).parent.parent / "tools"
    if tools_dir.exists():
        for tool_file in tools_dir.glob("*.py"):
            if tool_file.name != "__init__.py":
                module_name = f"tools.{tool_file.stem}"
                
                # Categorize by filename patterns
                if "gitlab" in tool_file.stem.lower():
                    if "gitlab" not in tool_modules:
                        tool_modules["gitlab"] = []
                    tool_modules["gitlab"].append(module_name)
                elif "sonar" in tool_file.stem.lower():
                    if "sonarqube" not in tool_modules:
                        tool_modules["sonarqube"] = []
                    tool_modules["sonarqube"].append(module_name)
                else:
                    # Generic tools
                    if "generic" not in tool_modules:
                        tool_modules["generic"] = []
                    tool_modules["generic"].append(module_name)
    
    return tool_modules


class ToolProvider(ABC):
    """Abstract base class for tool providers"""
    
    @abstractmethod
    def get_tools(self) -> List[Callable]:
        """Return list of tools provided by this provider"""
        pass
    
    def get_tool_names(self) -> List[str]:
        """Get names of tools for documentation - always dynamic"""
        return [extract_tool_description(tool) for tool in self.get_tools()]


class DynamicToolProvider(ToolProvider):
    """Completely dynamic tool provider that discovers tools automatically"""
    
    def __init__(self, category: str, modules: List[str] = None):
        self.category = category
        self.modules = modules or []
        self._tools_cache = None
    
    def get_tools(self) -> List[Callable]:
        """Get all available tools for this category"""
        if self._tools_cache is not None:
            return self._tools_cache
        
        tools = []
        for module_name in self.modules:
            discovered_tools = discover_tools_in_module(module_name)
            tools.extend(discovered_tools)
        
        self._tools_cache = tools
        return tools
    
    def refresh_tools(self):
        """Refresh tool cache to pick up new tools"""
        self._tools_cache = None


class ToolRegistry:
    """Completely dynamic tool registry that discovers everything automatically"""
    
    def __init__(self):
        self._providers: Dict[str, ToolProvider] = {}
        self._discover_and_register_providers()
    
    def _discover_and_register_providers(self):
        """Automatically discover and register all available tool providers"""
        available_modules = get_available_tool_modules()
        
        for category, modules in available_modules.items():
            provider = DynamicToolProvider(category, modules)
            self._providers[category] = provider
    
    def register_provider(self, name: str, provider: ToolProvider):
        """Register a custom tool provider"""
        self._providers[name] = provider
    
    def get_available_categories(self) -> List[str]:
        """Get all available tool categories"""
        return list(self._providers.keys())
    
    def get_tools_for_category(self, category: str) -> List[Callable]:
        """Get tools for a specific category"""
        if category in self._providers:
            return self._providers[category].get_tools()
        return []
    
    def get_tools_for_agent(self, agent_type: str, session_tools: List[Callable] = None) -> List[Callable]:
        """Get appropriate tools for a specific agent type - completely dynamic"""
        tools = []
        
        # Add session-specific tools (like tracked file tools)
        if session_tools:
            tools.extend(session_tools)
        
        # Dynamic tool assignment based on agent type and available providers
        agent_type_lower = agent_type.lower()
        
        # Define flexible mapping that can be extended via configuration
        category_mappings = {
            "pipeline": ["gitlab", "generic"],
            "quality": ["sonarqube", "generic"],
            # Could be extended with: "security": ["security", "generic"], etc.
        }
        
        # Get tools for relevant categories
        relevant_categories = category_mappings.get(agent_type_lower, ["generic"])
        
        for category in relevant_categories:
            if category in self._providers:
                category_tools = self._providers[category].get_tools()
                
                if category == "gitlab" and agent_type_lower == "quality":
                    # For quality agents, filter GitLab tools to only MR and search
                    filtered_tools = [
                        tool for tool in category_tools 
                        if hasattr(tool, '__name__') and 
                        any(keyword in tool.__name__ for keyword in ['merge_request', 'search', 'create_merge'])
                    ]
                    tools.extend(filtered_tools)
                else:
                    tools.extend(category_tools)
        
        return tools
    
    def get_capability_description(self, agent_type: str) -> str:
        """Generate dynamic capability description based on available tools"""
        capabilities = []
        
        # Get tools for this agent type
        agent_tools = self.get_tools_for_agent(agent_type, [])
        
        # Extract capabilities from actual tools
        for tool in agent_tools:
            capability = extract_tool_description(tool)
            if capability not in capabilities:
                capabilities.append(capability)
        
        # Add common session capabilities (these could also be discovered dynamically)
        session_capabilities = [
            "Access to previous analysis data and tracked files",
            "Session state management and context preservation"
        ]
        capabilities.extend(session_capabilities)
        
        if not capabilities:
            return "You have access to various analysis and integration tools."
        
        capability_text = "You have access to tools that provide:\n"
        for capability in capabilities:
            capability_text += f"- {capability}\n"
        
        capability_text += "\nUse the available tools as needed to gather information and implement solutions."
        
        return capability_text
    
    def refresh_all_providers(self):
        """Refresh all providers to pick up new tools"""
        for provider in self._providers.values():
            if hasattr(provider, 'refresh_tools'):
                provider.refresh_tools()
    
    def get_registry_info(self) -> Dict[str, Any]:
        """Get information about the current registry state"""
        info = {
            "categories": [],
            "total_tools": 0,
            "tools_by_category": {}
        }
        
        for category, provider in self._providers.items():
            tools = provider.get_tools()
            tool_count = len(tools)
            
            info["categories"].append(category)
            info["total_tools"] += tool_count
            info["tools_by_category"][category] = {
                "count": tool_count,
                "tools": [tool.__name__ for tool in tools if hasattr(tool, '__name__')]
            }
        
        return info


# Global registry instance - completely dynamic
tool_registry = ToolRegistry()
