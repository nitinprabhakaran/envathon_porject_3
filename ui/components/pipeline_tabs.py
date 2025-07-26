from typing import Dict, Any, Optional

class PipelineTabs:
    """Manage multiple pipeline failure tabs"""
    
    def __init__(self):
        self.tabs = {}
        self.active_tab = None
    
    def add_tab(self, session_id: str, session_data: Dict[str, Any]):
        """Add a new pipeline tab"""
        self.tabs[session_id] = {
            "id": session_id,
            "project_id": session_data.get("project_id"),
            "pipeline_id": session_data.get("pipeline_id"),
            "status": session_data.get("status", "active"),
            "unread_count": 0,
            "conversation_history": session_data.get("conversation_history", []),
            "metadata": session_data
        }
        
        # Auto-activate if first tab
        if not self.active_tab:
            self.active_tab = session_id
    
    def set_active(self, session_id: str):
        """Set the active tab"""
        if session_id in self.tabs:
            self.active_tab = session_id
            self.tabs[session_id]["unread_count"] = 0
    
    def get_active(self) -> Optional[Dict[str, Any]]:
        """Get the active tab data"""
        if self.active_tab and self.active_tab in self.tabs:
            return self.tabs[self.active_tab]
        return None
    
    def update_session(self, session_id: str, session_data: Dict[str, Any]):
        """Update session data"""
        if session_id not in self.tabs:
            self.add_tab(session_id, session_data)
        else:
            self.tabs[session_id].update(session_data)
    
    def increment_unread(self, session_id: str):
        """Increment unread count for a tab"""
        if session_id in self.tabs and session_id != self.active_tab:
            self.tabs[session_id]["unread_count"] += 1
    
    def close_tab(self, session_id: str):
        """Close a tab"""
        if session_id in self.tabs:
            del self.tabs[session_id]
            if self.active_tab == session_id:
                # Activate another tab if available
                self.active_tab = list(self.tabs.keys())[0] if self.tabs else None
    
    def get_all_tabs(self) -> Dict[str, Dict[str, Any]]:
        """Get all tabs"""
        return self.tabs