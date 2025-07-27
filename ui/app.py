import streamlit as st
import asyncio
from datetime import datetime, timezone
import time
from typing import Dict, Any, List
from components.cards import render_card
from components.quality_cards import render_quality_card
from utils.api_client import APIClient

# Page config
st.set_page_config(
    page_title="CI/CD Failure Assistant",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .stChatMessage {
        padding: 0.5rem 1rem;
        margin: 0.5rem 0;
    }
    .card-container {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 15px;
        margin: 10px 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .stButton > button {
        width: 100%;
        white-space: nowrap;
    }
    .session-item {
        padding: 0.5rem;
        margin: 0.25rem 0;
        border-radius: 4px;
        cursor: pointer;
        transition: background-color 0.2s;
    }
    .session-item:hover {
        background-color: #f0f0f0;
    }
    .session-item.active {
        background-color: #0066cc;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "pipeline"
if "selected_session" not in st.session_state:
    st.session_state.selected_session = None
if "api_client" not in st.session_state:
    st.session_state.api_client = APIClient()
if "sessions_cache" not in st.session_state:
    st.session_state.sessions_cache = {}

# Helper functions
def format_session_display(session: Dict[str, Any]) -> str:
    """Format session for display"""
    if session.get("session_type") == "quality":
        status_icon = "🚨" if session.get("quality_gate_status") == "ERROR" else "⚠️"
        return f"{status_icon} {session.get('project_name', 'Unknown')} ({session.get('total_issues', 0)} issues)"
    else:
        status_icon = "🔴" if session.get("status") == "active" else "✅"
        return f"{status_icon} {session.get('project_name', 'Unknown')}#{session.get('pipeline_id', 'Unknown')}"

def extract_quality_info(response: str) -> Dict[str, Any]:
    """Extract quality fix information from response"""
    info = {
        "issues_fixed": 0,
        "merge_request_created": False,
        "summary": response
    }
    
    if "merge request has been created successfully" in response.lower():
        info["merge_request_created"] = True
        # Extract number of issues fixed if mentioned
        import re
        match = re.search(r'(\d+)\s+sonarqube\s+issues', response.lower())
        if match:
            info["issues_fixed"] = int(match.group(1))
    
    return info

@st.cache_data(ttl=30)
def fetch_sessions():
    """Fetch active sessions with caching"""
    async def _fetch():
        return await st.session_state.api_client.get_active_sessions()
    return asyncio.run(_fetch())

async def load_session_data(session_id: str):
    """Load session data"""
    if session_id not in st.session_state.sessions_cache:
        session_data = await st.session_state.api_client.get_session(session_id)
        st.session_state.sessions_cache[session_id] = session_data
    return st.session_state.sessions_cache[session_id]

# Header
st.title("🔧 CI/CD Failure Assistant")

# Tab selection
tab1, tab2 = st.tabs(["🚀 Pipeline Failures", "📊 Quality Issues"])

# Get sessions
sessions = fetch_sessions()
pipeline_sessions = [s for s in sessions if s.get("session_type", "pipeline") == "pipeline"]
quality_sessions = [s for s in sessions if s.get("session_type") == "quality"]

with tab1:
    if pipeline_sessions:
        # Use columns for layout
        col1, col2 = st.columns([1, 3])
        
        with col1:
            st.subheader("Active Pipelines")
            for session in pipeline_sessions:
                if st.button(
                    format_session_display(session),
                    key=f"pipe_{session['id']}",
                    use_container_width=True,
                    type="primary" if session['id'] == st.session_state.selected_session else "secondary"
                ):
                    st.session_state.selected_session = session['id']
                    st.rerun()
        
        with col2:
            if st.session_state.selected_session:
                session_data = asyncio.run(load_session_data(st.session_state.selected_session))
                
                # Session header
                st.subheader(f"Pipeline {session_data.get('pipeline_id')} - {session_data.get('project_name')}")
                
                # Metadata
                cols = st.columns(4)
                cols[0].metric("Branch", session_data.get('branch', 'N/A'))
                cols[1].metric("Stage", session_data.get('failed_stage', 'N/A'))
                cols[2].metric("Status", session_data.get('status', 'Unknown'))
                cols[3].metric("Error Type", session_data.get('error_type', 'N/A'))
                
                # Chat interface
                st.divider()
                messages = session_data.get('conversation_history', [])
                
                # Display messages
                for msg in messages:
                    if msg.get('role') == 'system':
                        continue
                    
                    with st.chat_message(msg['role']):
                        st.write(msg.get('content', ''))
                        
                        # Render cards if present
                        if 'cards' in msg:
                            for card in msg['cards']:
                                render_card(card, session_data)
                
                # Chat input
                if prompt := st.chat_input("Ask about the failure..."):
                    with st.spinner("Analyzing..."):
                        response = asyncio.run(
                            st.session_state.api_client.send_message(
                                st.session_state.selected_session,
                                prompt
                            )
                        )
                        st.rerun()
            else:
                st.info("Select a pipeline from the left to view details")
    else:
        st.info("No active pipeline failures")

with tab2:
    if quality_sessions:
        col1, col2 = st.columns([1, 3])
        
        with col1:
            st.subheader("Quality Sessions")
            for session in quality_sessions:
                if st.button(
                    format_session_display(session),
                    key=f"qual_{session['id']}",
                    use_container_width=True,
                    type="primary" if session['id'] == st.session_state.selected_session else "secondary"
                ):
                    st.session_state.selected_session = session['id']
                    st.rerun()
        
        with col2:
            if st.session_state.selected_session:
                session_data = asyncio.run(load_session_data(st.session_state.selected_session))
                
                # Session header
                st.subheader(f"Quality Analysis - {session_data.get('project_name')}")
                
                # Quality metrics
                cols = st.columns(4)
                cols[0].metric("Quality Gate", session_data.get('quality_gate_status', 'ERROR'))
                cols[1].metric("Total Issues", session_data.get('total_issues', 0))
                cols[2].metric("Critical", session_data.get('critical_issues', 0))
                cols[3].metric("Major", session_data.get('major_issues', 0))
                
                # Chat interface
                st.divider()
                messages = session_data.get('conversation_history', [])
                
                for msg in messages:
                    if msg.get('role') == 'system':
                        continue
                    
                    with st.chat_message(msg['role']):
                        content = msg.get('content', '')
                        
                        # For quality responses, extract and display key info
                        if msg['role'] == 'assistant' and session_data.get('session_type') == 'quality':
                            info = extract_quality_info(content)
                            if info['merge_request_created']:
                                st.success(f"✅ Fixed {info['issues_fixed']} issues and created merge request")
                            st.markdown(content)
                        else:
                            st.write(content)
                
                # Chat input
                if prompt := st.chat_input("Ask about quality issues..."):
                    with st.spinner("Analyzing..."):
                        response = asyncio.run(
                            st.session_state.api_client.send_message(
                                st.session_state.selected_session,
                                prompt
                            )
                        )
                        st.rerun()
            else:
                st.info("Select a quality session from the left")
    else:
        st.info("No active quality issues")

# Auto-refresh
if st.sidebar.button("🔄 Refresh", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

# Check URL params
if "session" in st.query_params:
    session_id = st.query_params["session"]
    if session_id != st.session_state.selected_session:
        st.session_state.selected_session = session_id
        st.rerun()