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

# CSS for better styling
st.markdown("""
<style>
    /* Card containers */
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
if "messages" not in st.session_state:
    st.session_state.messages = {}

async def fetch_sessions():
    """Fetch active sessions from API"""
    sessions = await st.session_state.api_client.get_active_sessions()
    return sessions

async def load_session(session_id: str):
    """Load complete session data from API"""
    session_data = await st.session_state.api_client.get_session(session_id)
    
    # Update the tabs with complete session data
    st.session_state.pipeline_tabs.update_session(session_id, session_data)
    st.session_state.selected_session_id = session_id
    st.session_state.pipeline_tabs.set_active(session_id)
    
    # Store messages for native chat
    if session_id not in st.session_state.messages:
        st.session_state.messages[session_id] = []
    
    # Convert conversation history to chat messages
    conv_history = session_data.get("conversation_history", [])
    st.session_state.messages[session_id] = conv_history

async def send_message(session_id: str, message: str):
    """Send a message to the agent"""
    response = await st.session_state.api_client.send_message(session_id, message)
    
    # Add user message
    user_msg = {
        "role": "user",
        "content": message,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    st.session_state.messages[session_id].append(user_msg)
    
    # Add assistant response
    assistant_msg = {
        "role": "assistant",
        "content": response.get("response", ""),
        "cards": response.get("cards", []),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    st.session_state.messages[session_id].append(assistant_msg)
    
    # Update pipeline tabs
    active_session = st.session_state.pipeline_tabs.get_active()
    if active_session:
        active_session["conversation_history"] = st.session_state.messages[session_id]

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
    if session_id != st.session_state.selected_session_id:
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
        session_id = active_session['id']
        
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
        
        # Chat container
        chat_container = st.container(height=600)
        
        # Display messages
        with chat_container:
            messages = st.session_state.messages.get(session_id, [])
            
            for msg in messages:
                if msg.get("role") == "system":
                    continue  # Skip system messages
                    
                # Use native chat message
                with st.chat_message(msg["role"]):
                    # Show cards if present
                    if "cards" in msg and msg["cards"]:
                        # Deduplicate cards by type
                        seen_types = set()
                        unique_cards = []
                        for card in msg["cards"]:
                            card_type = card.get("type", "default")
                            if card_type not in seen_types or card_type == "error":
                                seen_types.add(card_type)
                                unique_cards.append(card)
                        
                        for card in unique_cards:
                            render_card(card, active_session)
                    elif msg.get("content"):
                        # Only show content if no cards
                        st.write(msg["content"])
        
        # Chat input
        if prompt := st.chat_input("Ask about the failure or request a fix..."):
            # Add user message to chat
            with chat_container:
                with st.chat_message("user"):
                    st.write(prompt)
            
            # Get response
            with st.spinner("Analyzing..."):
                asyncio.run(send_message(session_id, prompt))
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