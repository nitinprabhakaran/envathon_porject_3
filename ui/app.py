import streamlit as st
import asyncio
from datetime import datetime, timezone
import json
from components.cards import render_card
from components.pipeline_tabs import PipelineTabs
from utils.api_client import APIClient

# Page config
st.set_page_config(
    page_title="CI/CD Failure Assistant",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Dark theme CSS fix
st.markdown("""
<style>
    /* Dark theme fix for chat messages */
    .chat-message {
        padding: 10px;
        margin: 5px 0;
        border-radius: 8px;
        color: #000000;  /* Black text */
    }
    .user-message {
        background-color: #e3f2fd;
        text-align: right;
        color: #000000;
    }
    .assistant-message {
        background-color: #f5f5f5;
        color: #000000;
    }
    
    /* Fix for card containers */
    .card-container {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 15px;
        margin: 10px 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        color: #000000;
    }
    
    /* Pipeline tab styling */
    .pipeline-tab {
        padding: 10px 15px;
        margin: 0 5px;
        border-radius: 5px;
        cursor: pointer;
        background-color: #f0f0f0;
        border: 1px solid #ddd;
        color: #000000;
    }
    .pipeline-tab.active {
        background-color: #0066cc;
        color: white;
    }
    .pipeline-tab .badge {
        background-color: #ff4444;
        color: white;
        padding: 2px 6px;
        border-radius: 10px;
        font-size: 12px;
        margin-left: 5px;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "pipeline_tabs" not in st.session_state:
    st.session_state.pipeline_tabs = PipelineTabs()
if "api_client" not in st.session_state:
    st.session_state.api_client = APIClient()
if "sessions_data" not in st.session_state:
    st.session_state.sessions_data = []
if "selected_session_id" not in st.session_state:
    st.session_state.selected_session_id = None
if "is_loading" not in st.session_state:
    st.session_state.is_loading = False

async def fetch_sessions():
    """Fetch active sessions from API"""
    sessions = await st.session_state.api_client.get_active_sessions()
    return sessions

async def load_session(session_id: str):
    """Load complete session data from API"""
    session_data = await st.session_state.api_client.get_session(session_id)
    
    # Debug logging
    print(f"Loading session {session_id}, received data:")
    print(f"  project_id: {session_data.get('project_id')}")
    print(f"  pipeline_id: {session_data.get('pipeline_id')}")
    print(f"  conversation_history length: {len(session_data.get('conversation_history', []))}")
    
    # Update the tabs with complete session data
    st.session_state.pipeline_tabs.update_session(session_id, session_data)
    st.session_state.selected_session_id = session_id
    st.session_state.pipeline_tabs.set_active(session_id)

async def send_message(session_id: str, message: str):
    """Send a message to the agent"""
    st.session_state.is_loading = True
    response = await st.session_state.api_client.send_message(session_id, message)
    
    # Update local state
    active_session = st.session_state.pipeline_tabs.get_active()
    if active_session:
        # Ensure conversation_history is a list
        if not isinstance(active_session.get("conversation_history"), list):
            active_session["conversation_history"] = []
            
        active_session["conversation_history"].append({
            "role": "user",
            "content": message,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        active_session["conversation_history"].append({
            "role": "assistant",
            "content": response.get("response", ""),
            "cards": response.get("cards", []),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    st.session_state.is_loading = False

def calculate_duration(start_time: datetime) -> str:
    """Calculate duration from start time"""
    now = datetime.now(timezone.utc)
    if isinstance(start_time, str):
        try:
            start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        except:
            return "N/A"
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    duration = now - start_time
    hours = duration.seconds // 3600
    minutes = (duration.seconds % 3600) // 60
    return f"{hours}h {minutes}m"

# Header
col1, col2, col3 = st.columns([3, 2, 1])
with col1:
    st.title("🔧 CI/CD Failure Assistant")
with col2:
    st.empty()
with col3:
    if st.button("🔄 Refresh", key="refresh_btn"):
        st.rerun()

# Check for session_id parameter in URL
query_params = st.query_params
if "session" in query_params:
    session_id = query_params["session"]
    # Load this specific session
    if session_id not in [s['id'] for s in st.session_state.sessions_data]:
        # Add to sessions data and load it
        asyncio.run(load_session(session_id))

# Auto-load sessions on startup
if not st.session_state.sessions_data:
    with st.spinner("Loading sessions..."):
        st.session_state.sessions_data = asyncio.run(fetch_sessions())

# Main layout
sidebar_col, main_col, details_col = st.columns([2, 5, 2])

# Left Sidebar - Pipeline List
with sidebar_col:
    st.subheader("📋 Pipeline Failures")
    
    # Refresh button
    if st.button("🔄 Refresh Sessions", key="refresh_sessions_btn", use_container_width=True):
        with st.spinner("Refreshing..."):
            st.session_state.sessions_data = asyncio.run(fetch_sessions())
            st.rerun()
    
    st.divider()
    
    # Display sessions
    seen_ids = set()
    for session in st.session_state.sessions_data:
        session_id = session.get('id')
        if not session_id or session_id in seen_ids:
            continue
        seen_ids.add(session_id)
        
        # Get project and pipeline info
        project_id = session.get('project_id', 'Unknown')
        pipeline_id = session.get('pipeline_id', 'Unknown')
        project_name = session.get('project_name', f'Project {project_id}')
        
        status_icon = "🔴" if session.get("status") == "active" else "✅"
        unread = session.get("unread_count", 0)
        badge = f"({unread})" if unread > 0 else ""
        
        # Create unique key for each button
        button_key = f"pipeline_{session_id}"
        button_label = f"{status_icon} {project_name}#{pipeline_id} {badge}"
        
        # Highlight active session
        is_active = st.session_state.selected_session_id == session_id
        
        if st.button(
            button_label, 
            key=button_key, 
            use_container_width=True,
            type="primary" if is_active else "secondary"
        ):
            asyncio.run(load_session(session_id))
            st.rerun()

# Main Content - Active Conversation
with main_col:
    active_session = st.session_state.pipeline_tabs.get_active()
    
    if active_session:
        # Extract session details
        project_name = active_session.get('project_name', active_session.get('project_id', 'Unknown'))
        pipeline_id = active_session.get('pipeline_id', 'Unknown')
        branch = active_session.get('branch', 'N/A')
        source = active_session.get('pipeline_source', 'N/A')
        pipeline_url = active_session.get('pipeline_url')

        st.subheader(f"Pipeline {pipeline_id} - {project_name}")
        
        # Pipeline info with link
        info_cols = st.columns(4)
        with info_cols[0]:
            st.caption(f"**Branch:** {branch}")
        with info_cols[1]:
            st.caption(f"**Source:** {source}")
        with info_cols[2]:
            st.caption(f"**Job:** {active_session.get('job_name', 'N/A')}")
        with info_cols[3]:
            if pipeline_url:
                st.caption(f"[View in GitLab →]({pipeline_url})")
        
        st.divider()
        
        # Conversation history
        chat_container = st.container()
        with chat_container:
            conversation_history = active_session.get("conversation_history", [])
            
            if not conversation_history:
                st.info("No conversation history yet. The agent should analyze the failure soon...")
            else:
                for msg in conversation_history:
                    if isinstance(msg, dict):
                        if msg.get("role") == "user":
                            st.markdown(
                                f'<div class="chat-message user-message"><strong>You:</strong><br>{msg["content"]}</div>',
                                unsafe_allow_html=True
                            )
                        elif msg.get("role") == "assistant":
                            # Show assistant message content if no cards
                            if msg.get("content") and not msg.get("cards"):
                                st.markdown(
                                    f'<div class="chat-message assistant-message"><strong>Assistant:</strong><br>{msg["content"]}</div>',
                                    unsafe_allow_html=True
                                )
                            
                            # Render cards if present
                            if "cards" in msg and msg["cards"]:
                                for card in msg["cards"]:
                                    render_card(card, active_session)
        
        # Show loading spinner if waiting for response
        if st.session_state.is_loading:
            with st.spinner("Analyzing..."):
                st.empty()
        
        # Input area
        with st.form("chat_input", clear_on_submit=True):
            col1, col2 = st.columns([5, 1])
            with col1:
                user_input = st.text_input(
                    "Message",
                    placeholder="Ask about the failure or request a fix...",
                    label_visibility="collapsed"
                )
            with col2:
                send = st.form_submit_button("Send", use_container_width=True)
            
            if send and user_input:
                asyncio.run(send_message(active_session['id'], user_input))
                st.rerun()
    else:
        st.info("👈 Select a pipeline failure from the left sidebar to start analyzing")
        if st.session_state.sessions_data:
            st.caption(f"Found {len(st.session_state.sessions_data)} active sessions")

# Right Sidebar - Context Panel
with details_col:
    if active_session:
        st.subheader("📊 Pipeline Details")
        
        # Get values with defaults
        status = active_session.get("status", "Unknown")
        failed_stage = active_session.get("failed_stage", "N/A")
        error_type = active_session.get("error_type", "N/A")
        
        # Status metrics
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Status", status.title())
        with col2:
            st.metric("Stage", failed_stage)
        
        st.metric("Error Type", error_type.replace("_", " ").title())
        
        # Error signature if available
        if error_sig := active_session.get("error_signature"):
            with st.expander("Error Signature"):
                st.code(error_sig[:200] + "..." if len(error_sig) > 200 else error_sig)
        
        st.divider()
        
        st.subheader("⏱️ Session Info")
        created = active_session.get("created_at", datetime.now().isoformat())
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created.replace('Z', '+00:00'))
            except:
                created = datetime.now(timezone.utc)
        
        st.text(f"Started: {created.strftime('%H:%M')}")
        st.text(f"Duration: {calculate_duration(created)}")
        
        # Session ID (for debugging)
        with st.expander("Session ID"):
            st.code(active_session.get('id', 'N/A'))
        
        st.divider()
        
        st.subheader("🛠️ Applied Fixes")
        fixes = active_session.get("applied_fixes", [])
        if isinstance(fixes, str):
            try:
                fixes = json.loads(fixes)
            except:
                fixes = []
        
        if fixes:
            for fix in fixes:
                if isinstance(fix, dict):
                    fix_type = fix.get('type', fix.get('fix_type', 'Fix'))
                    fix_desc = fix.get('description', 'Applied')
                    st.success(f"✓ {fix_type}: {fix_desc}")
                else:
                    st.success(f"✓ Fix applied")
        else:
            st.text("No fixes applied yet")
        
        # Successful fixes
        successful = active_session.get("successful_fixes", [])
        if successful:
            st.divider()
            st.subheader("✅ Successful Fixes")
            for fix in successful:
                if isinstance(fix, dict):
                    st.success(f"✓ {fix.get('description', 'Fix successful')}")