import streamlit as st
from typing import Dict, Any, Optional
import time
from loguru import logger

def render_card(content: str, session_data: Optional[Dict[str, Any]] = None):
    """Render content as markdown"""
    with st.container():
        st.markdown(content)
        
        # Add action buttons based on content
        if "merge request" in content.lower() and "create" in content.lower():
            if st.button("Send to Agent: Create MR", key=f"mr_{time.time()}"):
                handle_action({"action": "create_mr"}, session_data)

def handle_action(action: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Handle actions through conversation"""
    import asyncio
    from utils.api_client import APIClient
    
    action_type = action.get('action')
    
    if action_type == "create_mr":
        message = "Create the merge request with the fixes you suggested"
    else:
        message = f"Execute: {action_type}"
    
    with st.spinner("Processing..."):
        client = APIClient()
        result = asyncio.run(client.send_message(
            session_data['id'],
            message
        ))
        st.rerun()