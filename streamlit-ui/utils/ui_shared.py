"""Shared UI utilities compatible with existing environment structure"""
import streamlit as st
import asyncio
import time
import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from functools import wraps

from .api_client import UnifiedAPIClient
from .logger import setup_logger

log = setup_logger()


def parse_message_content(content: Any) -> str:
    """Parse message content from various formats (string, JSON, structured)"""
    if isinstance(content, str):
        # Try to parse JSON string if it looks like JSON
        if content.strip().startswith('{') or content.strip().startswith('['):
            try:
                parsed = json.loads(content)
                return parse_message_content(parsed)  # Recursive call for parsed JSON
            except json.JSONDecodeError:
                return content
        return content
    
    elif isinstance(content, dict):
        # Handle dictionary format
        if "text" in content:
            return content["text"]
        elif "message" in content:
            return content["message"]
        elif "content" in content:
            return parse_message_content(content["content"])
        else:
            return str(content)
    
    elif isinstance(content, list):
        # Handle list format (like the structure you showed)
        if len(content) > 0:
            if isinstance(content[0], dict) and "text" in content[0]:
                return content[0]["text"]
            else:
                return parse_message_content(content[0])
        return ""
    
    else:
        return str(content)


def init_session_state(api_url: str = None):
    """Initialize session state with API client compatible with existing setup"""
    defaults = {
        "api_client": UnifiedAPIClient(),
        "selected_project": None,
        "selected_failure": None,
        "selected_pipeline_session": None,
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
        api_client = UnifiedAPIClient()
        return asyncio.run(api_client.get_active_sessions())
    except Exception as e:
        log.error(f"Failed to fetch sessions: {e}")
        return []


def render_session_status(session: Dict[str, Any], session_type: str = "pipeline") -> Tuple[str, str, str]:
    """Render session status consistently across pages"""
    # Check for new status field first
    status = session.get("status")
    if status:
        if status == "resolved":
            return "🟢", "Resolved", "success"
        elif status == "in_progress":
            return "🟡", "In Progress", "warning"
        elif status == "failed":
            return "🔴", "Failed", "error"
        elif status == "pending":
            return "🟠", "Pending", "info"
    
    # Fallback to legacy fix attempts analysis
    time_remaining = calculate_time_remaining(session.get('expires_at'))
    fix_attempts = session.get("webhook_data", {}).get("fix_attempts", [])
    
    # Determine status and colors from fix attempts
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
    """Render comprehensive fix attempts information with enhanced details"""
    if not fix_attempts:
        return
    
    col_iter1, col_iter2 = st.columns([3, 1])
    
    with col_iter1:
        pending_attempts = [att for att in fix_attempts if att.get("status") == "pending"]
        successful_attempts = [att for att in fix_attempts if att.get("status") == "success"]
        failed_attempts = [att for att in fix_attempts if att.get("status") == "failed"]
        
        # Enhanced status display
        total_attempts = len(fix_attempts)
        max_attempts = 5  # From config
        
        if successful_attempts:
            st.success(f"✅ Fix Iterations: {total_attempts}/{max_attempts} ({len(successful_attempts)} successful)")
        elif pending_attempts:
            st.warning(f"🔄 Fix Iterations: {total_attempts}/{max_attempts} (Checking status...)")
        elif failed_attempts and total_attempts >= max_attempts:
            st.error(f"❌ Max attempts reached: {total_attempts}/{max_attempts} (all failed)")
        elif failed_attempts:
            st.error(f"❌ Fix Iterations: {total_attempts}/{max_attempts} (all failed so far)")
        else:
            st.info(f"📝 Fix Iterations: {total_attempts}/{max_attempts}")
    
    with col_iter2:
        with st.expander("Fix History", expanded=len(fix_attempts) <= 3):
            for i, attempt in enumerate(fix_attempts):
                # Enhanced status icons and information
                status = attempt.get("status", "pending")
                if status == "success":
                    status_icon = "✅"
                    status_color = "green"
                elif status == "failed":
                    status_icon = "❌"
                    status_color = "red"
                else:  # pending
                    status_icon = "⏳"
                    status_color = "orange"
                
                # Attempt header
                attempt_num = attempt.get("attempt_number", i + 1)
                mr_id = attempt.get("mr_id") or attempt.get("merge_request_id", "N/A")
                
                with st.container():
                    col_status, col_details = st.columns([1, 3])
                    
                    with col_status:
                        st.markdown(f"**{status_icon} #{attempt_num}**")
                    
                    with col_details:
                        # Branch info
                        branch = attempt.get("branch") or attempt.get("branch_name", "N/A")
                        st.caption(f"**Branch:** `{branch}`")
                        
                        # MR info
                        if mr_id != "N/A" and attempt.get("mr_url"):
                            st.caption(f"**MR:** [!{mr_id}]({attempt['mr_url']})")
                        elif mr_id != "N/A":
                            st.caption(f"**MR:** !{mr_id}")
                        else:
                            st.caption(f"**MR:** Not created yet")
                        
                        # Status and timing
                        st.caption(f"**Status:** {status.title()}")
                        
                        # Show timestamps
                        if attempt.get("created_at"):
                            created = datetime.fromisoformat(attempt["created_at"].replace('Z', '+00:00'))
                            st.caption(f"**Started:** {created.strftime('%H:%M %b %d')}")
                        
                        if status == "success" and attempt.get("succeeded_at"):
                            succeeded = datetime.fromisoformat(attempt["succeeded_at"].replace('Z', '+00:00'))
                            st.caption(f"**Completed:** {succeeded.strftime('%H:%M %b %d')}")
                        elif status == "failed" and attempt.get("failed_at"):
                            failed = datetime.fromisoformat(attempt["failed_at"].replace('Z', '+00:00'))
                            st.caption(f"**Failed:** {failed.strftime('%H:%M %b %d')}")
                        
                        # Show error message for failed attempts
                        if status == "failed" and attempt.get("error_message"):
                            with st.expander(f"Error Details", expanded=False):
                                st.text(attempt["error_message"])
                    
                    # Add separator except for last item
                    if i < len(fix_attempts) - 1:
                        st.divider()


def render_session_details_card(session: Dict[str, Any]) -> None:
    """Render comprehensive session details in an expandable card"""
    session_id = session.get("session_id", "Unknown")
    
    with st.expander(f"📋 Session Details: {session_id[:8]}...", expanded=False):
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Session Information**")
            st.caption(f"**ID:** `{session_id}`")
            
            created_at = session.get("created_at")
            if created_at:
                created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                st.caption(f"**Created:** {created_time.strftime('%H:%M %b %d, %Y')}")
            
            expires_at = session.get("expires_at")
            if expires_at:
                expires_time = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                st.caption(f"**Expires:** {expires_time.strftime('%H:%M %b %d, %Y')}")
            
            # Show current fix branch if active
            current_fix_branch = session.get("current_fix_branch")
            if current_fix_branch:
                st.caption(f"**Current Fix Branch:** `{current_fix_branch}`")
            
            # Show fix iteration
            fix_iteration = session.get("fix_iteration", 0)
            if fix_iteration > 0:
                st.caption(f"**Fix Iteration:** {fix_iteration}/5")
        
        with col2:
            st.markdown("**Status Information**")
            
            # Status details
            status = session.get("status", "unknown")
            st.caption(f"**Status:** {status.title()}")
            
            # Resolution info if resolved
            if status == "resolved":
                resolved_at = session.get("resolved_at")
                if resolved_at:
                    resolved_time = datetime.fromisoformat(resolved_at.replace('Z', '+00:00'))
                    st.caption(f"**Resolved:** {resolved_time.strftime('%H:%M %b %d, %Y')}")
                
                resolution_method = session.get("resolution_method")
                if resolution_method:
                    st.caption(f"**Resolution:** {resolution_method.replace('_', ' ').title()}")
            
            # Quality metrics
            if session.get("quality_gate_passed"):
                st.caption("🎯 **Quality Gate:** Passed")
            elif session.get("quality_gate_passed") is False:
                st.caption("⚠️ **Quality Gate:** Failed")
            
            # Coverage if available
            coverage = session.get("coverage_percentage")
            if coverage is not None:
                if coverage >= 80:
                    st.caption(f"📈 **Coverage:** {coverage}% ✅")
                else:
                    st.caption(f"📉 **Coverage:** {coverage}% ⚠️")


def render_pipeline_info_card(pipeline_data: Dict[str, Any]) -> None:
    """Render pipeline information in a compact card"""
    if not pipeline_data:
        return
    
    status = pipeline_data.get("status", "unknown")
    
    with st.container():
        col_status, col_info = st.columns([1, 2])
        
        with col_status:
            if status == "success":
                st.success("✅ Passed")
            elif status == "failed":
                st.error("❌ Failed")
            elif status in ["running", "pending"]:
                st.warning("🔄 Running")
            elif status == "canceled":
                st.warning("⏹️ Canceled")
            else:
                st.info(f"📋 {status.title()}")
        
        with col_info:
            # Pipeline ID and URL
            pipeline_id = pipeline_data.get("id")
            pipeline_url = pipeline_data.get("web_url")
            
            if pipeline_id and pipeline_url:
                st.caption(f"[Pipeline #{pipeline_id}]({pipeline_url})")
            elif pipeline_id:
                st.caption(f"Pipeline #{pipeline_id}")
            
            # Duration and stage info
            if pipeline_data.get("duration"):
                duration = pipeline_data["duration"]
                st.caption(f"Duration: {duration}s")
            
            if status == "failed" and pipeline_data.get("failed_stage"):
                st.caption(f"Failed: {pipeline_data['failed_stage']}")


def render_quality_info_card(quality_data: Dict[str, Any]) -> None:
    """Render quality analysis information in a compact card"""
    if not quality_data:
        return
    
    status = quality_data.get("status", "unknown")
    
    with st.container():
        col_status, col_metrics = st.columns([1, 2])
        
        with col_status:
            if status == "passed":
                st.success("✅ Passed")
            elif status == "failed":
                st.error("❌ Issues")
            elif status in ["running", "analyzing"]:
                st.warning("🔍 Analyzing")
            else:
                st.info(f"📊 {status.title()}")
        
        with col_metrics:
            # Coverage
            if quality_data.get("coverage"):
                coverage = quality_data["coverage"]
                st.caption(f"Coverage: {coverage}%")
            
            # Issues summary
            issues = quality_data.get("issues", {})
            if issues:
                total_critical = issues.get("blocker", 0) + issues.get("critical", 0)
                if total_critical > 0:
                    st.caption(f"Critical Issues: {total_critical}")
                
                major_count = issues.get("major", 0)
                if major_count > 0:
                    st.caption(f"Major Issues: {major_count}")
            
            # Quality gate
            gate_status = quality_data.get("quality_gate")
            if gate_status:
                gate_icon = "✅" if gate_status == "passed" else "❌"
                st.caption(f"Quality Gate: {gate_icon}")


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
                    # Parse the response content properly
                    response_text = parse_message_content(response.get("response", ""))
                    st.write(response_text)
                    
                    if response.get("merge_request_url"):
                        st.success(f"✅ MR Created: {response['merge_request_url']}")
            
            st.rerun()


def render_action_buttons(session_id: str, mr_url: Optional[str], fix_attempts: List[Dict[str, Any]], 
                         current_branch: str = "", agent_type: str = "pipeline", session_status: str = None) -> None:
    """Render action buttons consistently based on session state"""
    col_btn1, col_btn2 = st.columns([1, 1])
    
    # Check session status first
    if session_status == "resolved":
        with col_btn1:
            st.success("✅ Session Resolved")
        with col_btn2:
            if mr_url:
                st.link_button("📄 View Final MR", mr_url, use_container_width=True, type="primary")
        return
    
    # Determine button logic for active sessions
    is_fix_branch = current_branch.startswith(f"fix/{agent_type}_")
    all_successful = all(att.get("status") == "success" for att in fix_attempts) if fix_attempts else False
    max_attempts_reached = len(fix_attempts) >= 5
    pending_attempts = [att for att in fix_attempts if att.get("status") == "pending"]
    
    with col_btn1:
        if pending_attempts:
            st.warning("⏳ Fix in progress...")
        elif all_successful and mr_url:
            st.link_button("📄 View MR", mr_url, use_container_width=True, type="primary")
        elif max_attempts_reached:
            st.error("❌ Max attempts reached")
        elif session_status == "failed":
            st.error("❌ Session failed")
        elif is_fix_branch and not mr_url:
            # Apply fix to existing branch
            if st.button("🔧 Apply Fix", use_container_width=True):
                with st.spinner("Applying fix to the existing branch... (This may take up to 2 minutes)"):
                    st.info("💡 The agent is analyzing the code and applying fixes. Please wait...")
                    try:
                        response = asyncio.run(
                            st.session_state.api_client.send_message(
                                session_id, 
                                f"Apply the fixes to the current feature branch. This is an iteration on our existing fix branch."
                            )
                        )
                        if response.get("merge_request_url"):
                            st.success(f"✅ Fix applied to existing MR")
                        st.rerun()
                    except Exception as e:
                        if "timeout" in str(e).lower():
                            st.warning("⏰ Request is taking longer than expected. Please check the session details in a moment.")
                        else:
                            st.error(f"❌ Error: {e}")
        elif len(fix_attempts) > 0 and not mr_url and not pending_attempts:
            # Retry button
            if st.button("🔄 Try Another Fix", use_container_width=True):
                with st.spinner(f"Creating additional {agent_type} fixes... (This may take up to 2 minutes)"):
                    st.info("🔍 The agent is analyzing the latest issues and creating additional fixes. Please wait...")
                    try:
                        message = "Please analyze the latest issues and create another fix targeting any remaining problems."
                        response = asyncio.run(
                            st.session_state.api_client.send_message(session_id, message)
                        )
                        if response.get("merge_request_url"):
                            st.success(f"✅ Additional fixes added")
                        st.rerun()
                    except Exception as e:
                        if "timeout" in str(e).lower():
                            st.warning("⏰ Request is taking longer than expected. Please check the session details in a moment.")
                        else:
                            st.error(f"❌ Error: {e}")
        else:
            # First attempt - create MR
            if st.button("🔀 Create MR", use_container_width=True):
                with st.spinner("Creating merge request... (This may take up to 2 minutes)"):
                    st.info("🚀 The agent is creating a merge request with all the fixes. Please wait...")
                    try:
                        message = "Create a merge request with all the fixes we discussed."
                        response = asyncio.run(
                            st.session_state.api_client.send_message(session_id, message)
                        )
                        if response.get("merge_request_url"):
                            st.success(f"✅ MR Created: {response['merge_request_url']}")
                        st.rerun()
                    except Exception as e:
                        if "timeout" in str(e).lower():
                            st.warning("⏰ Request is taking longer than expected. Please check the session details in a moment.")
                        else:
                            st.error(f"❌ Error: {e}")
    
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
