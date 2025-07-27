import streamlit as st
import asyncio
from datetime import datetime, timezone
import json, time
from components.cards import render_card
from components.quality_cards import render_quality_card
from components.pipeline_tabs import PipelineTabs
from utils.api_client import APIClient
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }
    
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #f0f0f0;
        border-radius: 4px;
        padding: 10px 20px;
        font-weight: 500;
    }
    
    .stTabs [aria-selected="true"] {
        background-color: #0066cc;
        color: white;
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
    
    /* Loading spinner improvements */
    .stSpinner > div {
        border-color: #0066cc !important;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state with better defaults
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
if "loading_session" not in st.session_state:
    st.session_state.loading_session = None
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = None
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "pipeline"

@st.cache_data(ttl=10)
def fetch_sessions_cached():
    """Fetch active sessions with caching"""
    async def _fetch():
        sessions = await st.session_state.api_client.get_active_sessions()
        logger.info(f"Fetched {len(sessions)} active sessions")
        return sessions
    return asyncio.run(_fetch())

async def load_session(session_id: str):
    """Load complete session data from API"""
    logger.info(f"Loading session: {session_id}")
    if st.session_state.loading_session == session_id:
        return
    
    st.session_state.loading_session = session_id
    
    try:
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
        
        # Set appropriate tab based on session type
        if session_data.get("session_type") == "quality":
            st.session_state.active_tab = "quality"
        else:
            st.session_state.active_tab = "pipeline"
    finally:
        st.session_state.loading_session = None

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
        st.cache_data.clear()
        st.rerun()

# Check for session_id and tab parameter in URL
query_params = st.query_params
if "session" in query_params:
    session_id = query_params["session"]
    if session_id != st.session_state.selected_session_id:
        asyncio.run(load_session(session_id))
    
    # Check for tab parameter
    if "tab" in query_params and query_params["tab"] == "quality":
        st.session_state.active_tab = "quality"

# Auto-load sessions on startup or refresh
now = time.time()
if not st.session_state.sessions_data or (st.session_state.last_refresh and now - st.session_state.last_refresh > 30):
    with st.spinner("Loading sessions..."):
        st.session_state.sessions_data = fetch_sessions_cached()
        st.session_state.last_refresh = now

# Main tabs
tab1, tab2 = st.tabs(["🚀 Pipeline Failures", "📊 Quality Issues"])

# Pipeline Failures Tab
with tab1:
    # Main layout
    sidebar_col, main_col, details_col = st.columns([2, 5, 2])
    
    # Filter sessions by type
    pipeline_sessions = [s for s in st.session_state.sessions_data if s.get("session_type", "pipeline") == "pipeline"]
    
    # Left Sidebar - Pipeline List
    with sidebar_col:
        st.subheader("📋 Pipeline Failures")
        
        if st.button("🔄 Refresh", key="refresh_pipeline_btn", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        st.divider()
        
        # Display pipeline sessions
        for session in pipeline_sessions:
            session_id = session.get('id')
            if not session_id:
                continue
            
            project_name = session.get('project_name', 'Unknown')
            pipeline_id = session.get('pipeline_id', 'Unknown')
            status_icon = "🔴" if session.get("status") == "active" else "✅"
            
            button_key = f"pipeline_{session_id}"
            button_label = f"{status_icon} {project_name}#{pipeline_id}"
            
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
        
        if active_session and active_session.get("session_type", "pipeline") == "pipeline":
            render_pipeline_conversation(active_session)
        else:
            st.info("👈 Select a pipeline failure from the left sidebar")
    
    # Right Sidebar - Context Panel
    with details_col:
        if active_session and active_session.get("session_type", "pipeline") == "pipeline":
            render_pipeline_details(active_session)

# Quality Issues Tab
with tab2:
    # Main layout
    sidebar_col, main_col, details_col = st.columns([2, 5, 2])
    
    # Filter sessions by type
    quality_sessions = [s for s in st.session_state.sessions_data if s.get("session_type") == "quality"]
    
    # Left Sidebar - Quality Sessions
    with sidebar_col:
        st.subheader("📊 Quality Sessions")
        
        if st.button("🔄 Refresh", key="refresh_quality_btn", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        st.divider()
        
        # Display quality sessions
        for session in quality_sessions:
            session_id = session.get('id')
            if not session_id:
                continue
            
            project_name = session.get('project_name', 'Unknown')
            gate_status = session.get('quality_gate_status', 'ERROR')
            total_issues = session.get('total_issues', 0)
            
            status_icon = "🚨" if gate_status == "ERROR" else "⚠️"
            
            button_key = f"quality_{session_id}"
            button_label = f"{status_icon} {project_name} ({total_issues} issues)"
            
            is_active = st.session_state.selected_session_id == session_id
            
            if st.button(
                button_label, 
                key=button_key, 
                use_container_width=True,
                type="primary" if is_active else "secondary"
            ):
                asyncio.run(load_session(session_id))
                st.session_state.active_tab = "quality"
                st.rerun()
    
    # Main Content - Quality Dashboard or Conversation
    with main_col:
        active_session = st.session_state.pipeline_tabs.get_active()
        
        if active_session and active_session.get("session_type") == "quality":
            render_quality_conversation(active_session)
        else:
            st.info("👈 Select a quality session from the left sidebar")
    
    # Right Sidebar - Quality Details
    with details_col:
        if active_session and active_session.get("session_type") == "quality":
            render_quality_details(active_session)

def render_pipeline_conversation(active_session):
    """Render pipeline failure conversation"""
    session_id = active_session['id']
    
    # Extract session details
    project_name = active_session.get('project_name', 'Unknown')
    pipeline_id = active_session.get('pipeline_id', 'Unknown')
    branch = active_session.get('branch', 'N/A')
    pipeline_url = active_session.get('pipeline_url')

    st.subheader(f"Pipeline {pipeline_id} - {project_name}")
    
    # Pipeline info
    info_cols = st.columns(4)
    with info_cols[0]:
        st.caption(f"**Branch:** {branch}")
    with info_cols[1]:
        st.caption(f"**Source:** {active_session.get('pipeline_source', 'N/A')}")
    with info_cols[2]:
        st.caption(f"**Job:** {active_session.get('job_name', 'N/A')}")
    with info_cols[3]:
        if pipeline_url:
            st.caption(f"[View in GitLab →]({pipeline_url})")
    
    st.divider()
    
    # Chat container
    render_conversation(active_session, session_id)

def render_quality_conversation(active_session):
    """Render quality analysis conversation"""
    session_id = active_session['id']
    
    # Extract session details
    project_name = active_session.get('project_name', 'Unknown')
    gate_status = active_session.get('quality_gate_status', 'ERROR')
    
    st.subheader(f"Quality Analysis - {project_name}")
    
    # Quality summary
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Quality Gate", gate_status, delta_color="inverse")
    with col2:
        st.metric("Total Issues", active_session.get('total_issues', 0))
    with col3:
        st.metric("Critical Issues", active_session.get('critical_issues', 0))
    
    st.divider()
    
    # Chat container
    render_conversation(active_session, session_id, quality_mode=True)

def render_conversation(active_session, session_id, quality_mode=False):
    """Render conversation with cards"""
    chat_container = st.container(height=600)
    
    # Display messages
    with chat_container:
        messages = st.session_state.messages.get(session_id, [])
        
        # Find the index of the last assistant message with solution cards
        last_solution_card_idx = -1
        for i in range(len(messages)-1, -1, -1):
            msg = messages[i]
            if msg.get("role") == "assistant" and msg.get("cards"):
                for card in msg["cards"]:
                    if card.get("type") == "solution":
                        last_solution_card_idx = i
                        break
                if last_solution_card_idx != -1:
                    break
        
        for idx, msg in enumerate(messages):
            if msg.get("role") == "system":
                continue
            
            with st.chat_message(msg["role"]):
                if "cards" in msg and msg["cards"]:
                    # Deduplicate cards by type
                    seen_types = set()
                    unique_cards = []
                    for card in msg["cards"]:
                        card_type = card.get("type", "default")
                        card_key = f"{card_type}_{card.get('title', '')}"
                        if card_key not in seen_types:
                            seen_types.add(card_key)
                            unique_cards.append(card)
                    
                    for card in unique_cards:
                        # Only show buttons on the last solution card
                        if card.get("type") == "solution" and idx != last_solution_card_idx:
                            card_copy = card.copy()
                            card_copy["actions"] = []
                            render_card(card_copy, active_session)
                        elif quality_mode and card.get("type") in ["quality_summary", "issue_category", "batch_fix"]:
                            render_quality_card(card, active_session)
                        else:
                            render_card(card, active_session)
                elif msg.get("content"):
                    st.write(msg["content"])
    
    # Chat input
    if prompt := st.chat_input("Ask about the issue...", key=f"chat_input_{session_id}"):
        with chat_container:
            with st.chat_message("user"):
                st.write(prompt)
        
        with st.spinner("Analyzing..."):
            asyncio.run(send_message(session_id, prompt))
            st.rerun()

def render_pipeline_details(active_session):
    """Render pipeline failure details"""
    st.subheader("📊 Pipeline Details")
    
    # Status metrics
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Status", active_session.get("status", "Unknown").title())
    with col2:
        st.metric("Stage", active_session.get("failed_stage", "N/A"))
    
    st.metric("Error Type", active_session.get("error_type", "N/A").replace("_", " ").title())
    
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
    
    # Applied fixes
    st.divider()
    st.subheader("🛠️ Applied Fixes")
    render_applied_fixes(active_session)

def render_quality_details(active_session):
    """Render quality analysis details"""
    st.subheader("📊 Quality Details")
    
    # Issue breakdown
    st.metric("Bugs", active_session.get("bugs_count", 0))
    st.metric("Vulnerabilities", active_session.get("vulnerabilities_count", 0))
    st.metric("Code Smells", active_session.get("code_smells_count", 0))
    
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
    
    # Applied fixes
    st.divider()
    st.subheader("🛠️ Quality Fixes")
    render_applied_fixes(active_session)

def render_applied_fixes(active_session):
    """Render applied fixes section"""
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
                if mr_url := fix.get('mr_url'):
                    st.success(f"✓ MR: [{fix_desc}]({mr_url})")
                else:
                    st.success(f"✓ {fix_type}: {fix_desc}")
            else:
                st.success(f"✓ Fix applied")
    else:
        st.text("No fixes applied yet")

if __name__ == "__main__":
    pass