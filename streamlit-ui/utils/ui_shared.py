"""Shared UI utilities compatible with existing environment structure"""
import streamlit as st
import asyncio
import time
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple
from functools import wraps

from .api_client import APIClient
from .logger import setup_logger

log = setup_logger()

def init_session_state(api_url: str = None):
    """Initialize session state with API client compatible with existing setup"""
    if 'api_client' not in st.session_state:
        # Use existing environment variable from docker-compose.yml
        base_url = api_url or os.getenv("STREAMLIT_API_URL", "http://strands-agent:8000")
        st.session_state.api_client = APIClient(base_url)
    
    # Initialize other session state variables
    if 'selected_pipeline_session' not in st.session_state:
        st.session_state.selected_pipeline_session = None
    if 'selected_quality_session' not in st.session_state:
        st.session_state.selected_quality_session = None

import streamlit as st
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from functools import wraps

from utils.api_client import APIClient
from utils.logger import setup_logger

log = setup_logger()


def init_session_state():
    """Initialize common session state variables"""
    defaults = {
        "api_client": APIClient(),
        "selected_project": None,
        "selected_failure": None,
        "selected_quality_session": None,
        "failure_groups": {},
        "quality_messages": {},
        "messages": {},
        "show_chat": {},
        "show_quality_chat": {}
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


@st.cache_data(ttl=60)  # Cache for 1 minute
def calculate_time_remaining(expires_at: str) -> str:
    """Calculate time remaining until session expires - cached for performance"""
    if not expires_at:
        return "Unknown"
    
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
    
    now = datetime.utcnow()
    if expires_at.tzinfo:
        expires_at = expires_at.replace(tzinfo=None)
    
    remaining = expires_at - now
    
    if remaining.total_seconds() <= 0:
        return "Expired"
    
    hours = int(remaining.total_seconds() // 3600)
    minutes = int((remaining.total_seconds() % 3600) // 60)
    
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


@st.cache_data(ttl=30)  # Cache for 30 seconds
def get_sessions_cached() -> List[Dict[str, Any]]:
    """Get sessions with caching to reduce API calls"""
    try:
        api_client = APIClient()
        return asyncio.run(api_client.get_active_sessions())
    except Exception as e:
        log.error(f"Failed to fetch sessions: {e}")
        return []


def render_session_status(session: Dict[str, Any], session_type: str = "pipeline") -> Tuple[str, str, str]:
    """Render session status consistently across pages"""
    time_remaining = calculate_time_remaining(session.get('expires_at'))
    fix_attempts = session.get("webhook_data", {}).get("fix_attempts", [])
    
    # Determine status and colors
    if fix_attempts:
        successful_fixes = [att for att in fix_attempts if att.get("status") == "success"]
        pending_fixes = [att for att in fix_attempts if att.get("status") == "pending"]
        
        if successful_fixes:
            return "🟢", "Fixed", "success"
        elif pending_fixes:
            return "🟡", "Fixing", "warning"
        else:
            return "🔴", "Failed", "error"
    else:
        # Color code based on time remaining
        if time_remaining == "Expired":
            return "🔴", "Expired", "error"
        elif "m" in time_remaining and "h" not in time_remaining:
            return "🟡", "Expiring Soon", "warning"
        else:
            return "🟢", "Active", "success"


def render_fix_attempts_info(fix_attempts: List[Dict[str, Any]]) -> None:
    """Render fix attempts information consistently"""
    if not fix_attempts:
        return
    
    col_iter1, col_iter2 = st.columns([3, 1])
    
    with col_iter1:
        pending_attempts = [att for att in fix_attempts if att.get("status") == "pending"]
        successful_attempts = [att for att in fix_attempts if att.get("status") == "success"]
        
        if successful_attempts:
            st.success(f"✅ Fix Iterations: {len(fix_attempts)}/5 ({len(successful_attempts)} successful)")
        elif pending_attempts:
            st.warning(f"🔄 Fix Iterations: {len(fix_attempts)}/5 (Checking status...)")
        else:
            st.error(f"❌ Fix Iterations: {len(fix_attempts)}/5 (all failed)")
    
    with col_iter2:
        with st.expander("Fix History"):
            for i, attempt in enumerate(fix_attempts):
                status_icon = "✅" if attempt.get("status") == "success" else "❌" if attempt.get("status") == "failed" else "⏳"
                st.text(f"{status_icon} Attempt {i+1}: MR #{attempt.get('mr_id', 'N/A')}")
                st.caption(f"Branch: {attempt.get('branch', 'N/A')}")
                st.caption(f"Status: {attempt.get('status', 'pending')}")


def render_chat_interface(session_id: str, messages: List[Dict[str, Any]], agent_type: str = "pipeline") -> None:
    """Render chat interface consistently across pages"""
    chat_key = f"show_{agent_type}_chat" if agent_type == "quality" else "show_chat"
    messages_key = f"{agent_type}_messages" if agent_type == "quality" else "messages"
    
    if st.session_state.get(chat_key, {}).get(session_id, False):
        st.markdown("### 💬 Ask a Question")
        
        # Chat input
        chat_input_key = f"chat_input_{agent_type}_{session_id}"
        if prompt := st.chat_input("Ask about this analysis...", key=chat_input_key):
            # Add user message
            if session_id not in st.session_state[messages_key]:
                st.session_state[messages_key][session_id] = []
            
            st.session_state[messages_key][session_id].append({
                "role": "user", 
                "content": prompt,
                "timestamp": datetime.now().isoformat()
            })
            
            # Get response
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    response = asyncio.run(
                        st.session_state.api_client.send_message(session_id, prompt)
                    )
                    response_text = response.get("response", "")
                    st.write(response_text)
                    
                    if response.get("merge_request_url"):
                        st.success(f"✅ MR Created: {response['merge_request_url']}")
            
            st.rerun()


def render_action_buttons(session_id: str, mr_url: Optional[str], fix_attempts: List[Dict[str, Any]], 
                         current_branch: str = "", agent_type: str = "pipeline") -> None:
    """Render action buttons consistently based on session state"""
    col_btn1, col_btn2 = st.columns([1, 1])
    
    # Determine button logic
    is_fix_branch = current_branch.startswith(f"fix/{agent_type}_")
    all_successful = all(att.get("status") == "success" for att in fix_attempts) if fix_attempts else False
    max_attempts_reached = len(fix_attempts) >= 5
    
    with col_btn1:
        if all_successful and mr_url:
            st.link_button("📄 View MR", mr_url, use_container_width=True, type="primary")
        elif max_attempts_reached:
            st.error("❌ Max attempts reached")
        elif is_fix_branch and not mr_url:
            # Apply fix to existing branch
            if st.button("🔧 Apply Fix", use_container_width=True):
                with st.spinner("Applying fix to the existing branch..."):
                    response = asyncio.run(
                        st.session_state.api_client.send_message(
                            session_id, 
                            f"Apply the fixes to the current feature branch. This is an iteration on our existing fix branch."
                        )
                    )
                    if response.get("merge_request_url"):
                        st.success(f"✅ Fix applied to existing MR")
                    st.rerun()
        elif len(fix_attempts) > 0 and not mr_url:
            # Retry button
            if st.button("🔄 Try Another Fix", use_container_width=True):
                with st.spinner(f"Creating additional {agent_type} fixes..."):
                    message = "Please analyze the latest issues and create another fix targeting any remaining problems."
                    response = asyncio.run(
                        st.session_state.api_client.send_message(session_id, message)
                    )
                    if response.get("merge_request_url"):
                        st.success(f"✅ Additional fixes added")
                    st.rerun()
        else:
            # First attempt - create MR
            if st.button("🔀 Create MR", use_container_width=True):
                with st.spinner("Creating merge request..."):
                    message = "Create a merge request with all the fixes we discussed."
                    response = asyncio.run(
                        st.session_state.api_client.send_message(session_id, message)
                    )
                    if response.get("merge_request_url"):
                        st.success(f"✅ MR Created: {response['merge_request_url']}")
                    st.rerun()
    
    with col_btn2:
        chat_key = f"show_{agent_type}_chat" if agent_type == "quality" else "show_chat"
        if st.button("💬 Ask Question", use_container_width=True):
            if chat_key not in st.session_state:
                st.session_state[chat_key] = {}
            st.session_state[chat_key][session_id] = not st.session_state[chat_key].get(session_id, False)


def check_auto_refresh_needed(sessions_data: Dict[str, Any]) -> bool:
    """Check if auto-refresh is needed based on pending operations"""
    for project_data in sessions_data.values():
        if isinstance(project_data, dict):
            # Pipeline sessions (grouped by branch)
            for branch_sessions in project_data.values():
                for session in branch_sessions:
                    fix_attempts = session.get("webhook_data", {}).get("fix_attempts", [])
                    if any(att.get("status") == "pending" for att in fix_attempts):
                        return True
        else:
            # Quality sessions (flat list)
            for session in project_data:
                fix_attempts = session.get("webhook_data", {}).get("fix_attempts", [])
                if any(att.get("status") == "pending" for att in fix_attempts):
                    return True
    return False


def render_common_page_header(title: str, icon: str, date_key: str = "date_range"):
    """Render common page header with navigation"""
    st.set_page_config(
        page_title=f"{title} - CI/CD Assistant",
        page_icon=icon,
        layout="wide"
    )
    
    st.title(f"{icon} {title}")
    
    # Navigation bar
    col_nav1, col_nav2, col_nav3 = st.columns([2, 2, 1])
    
    with col_nav1:
        date_range = st.date_input(
            "Date Range",
            value=(datetime.now() - timedelta(days=7), datetime.now()),
            key=date_key
        )
    
    with col_nav2:
        if "pipeline" in title.lower():
            filter_options = ["Failed", "Analyzing", "Fixed"]
            default_selection = ["Failed", "Analyzing"]
            filter_key = "status_filter"
        else:
            filter_options = ["Critical", "Major", "Minor"]
            default_selection = ["Critical", "Major"]
            filter_key = "severity_filter"
        
        status_filter = st.multiselect(
            "Filter",
            filter_options,
            default=default_selection,
            key=filter_key
        )
    
    with col_nav3:
        if st.button("🔄 Refresh", key=f"refresh_{date_key}"):
            st.session_state.last_refresh = None  # Force refresh
            st.rerun()
    
    return date_range, status_filter


# Performance monitoring decorator
def monitor_performance(func):
    """Decorator to monitor function performance"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            if duration > 2.0:  # Log slow operations
                log.warning(f"Slow operation: {func.__name__} took {duration:.2f}s")
            return result
        except Exception as e:
            duration = time.time() - start_time
            log.error(f"Error in {func.__name__} after {duration:.2f}s: {e}")
            raise
    return wrapper
