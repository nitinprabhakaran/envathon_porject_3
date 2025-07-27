import streamlit as st
import asyncio
from datetime import datetime, timezone
import json, time
from components.cards import render_card
from components.quality_cards import render_quality_card
from components.pipeline_tabs import PipelineTabs
from utils.api_client import APIClient
import logging
import re
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
    
    /* Fix button responsiveness */
    .stButton > button {
        width: 100%;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        background-color: #0056b3;
        transform: translateY(-1px);
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
if "loading_session" not in st.session_state:
    st.session_state.loading_session = None
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = None

# Helper functions
def parse_response_for_cards(response_text: str) -> tuple:
    """Parse AI response to extract confidence, solution and create cards"""
    cards = []
    
    # Extract confidence
    confidence_match = re.search(r'\*\*Confidence\*\*:\s*(\d+)%', response_text)
    confidence = int(confidence_match.group(1)) if confidence_match else 0
    
    # Extract root cause
    root_cause_match = re.search(r'\*\*Root Cause\*\*:\s*(.+?)(?=\n|$)', response_text)
    root_cause = root_cause_match.group(1) if root_cause_match else "Unknown"
    
    # Create analysis card
    cards.append({
        "type": "analysis",
        "title": "Pipeline Failure Analysis",
        "content": f"Root cause: {root_cause}",
        "confidence": confidence,
        "error_type": "build_failure"
    })
    
    # Check if there's a solution with high confidence
    if confidence >= 80 and "I can create a merge request" in response_text:
        # Extract solution details
        solution_match = re.search(r'### 💡 Solution\n(.+?)### Next Steps', response_text, re.DOTALL)
        solution_text = solution_match.group(1).strip() if solution_match else "Apply recommended fixes"
        
        cards.append({
            "type": "solution",
            "title": "Recommended Fix",
            "confidence": confidence,
            "estimated_time": "5-10 minutes",
            "content": solution_text[:200] + "..." if len(solution_text) > 200 else solution_text,
            "fix_type": "config",
            "actions": [
                {"label": "Apply Fix", "action": "apply_fix"},
                {"label": "Create MR", "action": "create_mr"}
            ]
        })
    
    return cards

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
        
        # Convert conversation history to chat messages with cards
        conv_history = session_data.get("conversation_history", [])
        messages = []
        for msg in conv_history:
            if msg.get("role") == "assistant" and "cards" not in msg and msg.get("content"):
                # Parse response to create cards
                cards = parse_response_for_cards(msg["content"])
                msg["cards"] = cards
            messages.append(msg)
        
        st.session_state.messages[session_id] = messages
        
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
    
    # Parse response for cards
    response_text = response.get("response", "")
    cards = parse_response_for_cards(response_text) if response_text else response.get("cards", [])
    
    # Add assistant response
    assistant_msg = {
        "role": "assistant",
        "content": response_text,
        "cards": cards,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    st.session_state.messages[session_id].append(assistant_msg)
    
    # Update pipeline tabs
    active_session = st.session_state.pipeline_tabs.get_active()
    if active_session:
        active_session["conversation_history"] = st.session_state.messages[session_id]
        st.session_state.pipeline_tabs.update_session(session_id, active_session)

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

def render_conversation(active_session, session_id, quality_mode=False):
    """Render conversation with cards"""
    chat_container = st.container(height=600)
    
    # Display messages
    with chat_container:
        messages = st.session_state.messages.get(session_id, [])
        
        for idx, msg in enumerate(messages):
            if msg.get("role") == "system":
                continue
            
            with st.chat_message(msg["role"]):
                # Display content
                if msg.get("content"):
                    st.markdown(msg["content"])
                
                # Display cards if present
                if "cards" in msg and msg["cards"]:
                    for card in msg["cards"]:
                        if quality_mode and card.get("type") in ["quality_summary", "issue_category", "batch_fix"]:
                            render_quality_card(card, active_session)
                        else:
                            render_card(card, active_session)
    
    # Chat input with unique key
    chat_key = f"chat_input_{session_id}_{int(time.time())}"
    if prompt := st.chat_input("Ask about the issue...", key=chat_key):
        with chat_container:
            with st.chat_message("user"):
                st.write(prompt)
        
        with st.spinner("Analyzing..."):
            asyncio.run(send_message(session_id, prompt))
            time.sleep(0.5)  # Small delay to ensure UI updates
            st.rerun()

# Header
col1, col2, col3 = st.columns([3, 2, 1])
with col1:
    st.title("🔧 CI/CD Failure Assistant")
with col3:
    if st.button("🔄 Refresh", key="refresh_btn", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# Check for session_id in URL
query_params = st.query_params
if "session" in query_params:
    session_id = query_params["session"]
    if session_id != st.session_state.selected_session_id:
        asyncio.run(load_session(session_id))

# Auto-load sessions
now = time.time()
if not st.session_state.sessions_data or (st.session_state.last_refresh and now - st.session_state.last_refresh > 30):
    with st.spinner("Loading sessions..."):
        st.session_state.sessions_data = fetch_sessions_cached()
        st.session_state.last_refresh = now

# Load selected session if any
if st.session_state.selected_session_id and st.session_state.selected_session_id not in st.session_state.messages:
    asyncio.run(load_session(st.session_state.selected_session_id))

# Main tabs
tab1, tab2 = st.tabs(["🚀 Pipeline Failures", "📊 Quality Issues"])

# Pipeline Failures Tab
with tab1:
    # Filter sessions by type
    pipeline_sessions = [s for s in st.session_state.sessions_data if s.get("session_type", "pipeline") == "pipeline"]
    
    # Main layout
    sidebar_col, main_col, details_col = st.columns([2, 5, 2])
    
    # Left Sidebar - Pipeline List
    with sidebar_col:
        st.subheader("📋 Pipeline Failures")
        
        if st.button("🔄 Refresh List", key="refresh_pipeline_btn", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        st.divider()
        
        # Display pipeline sessions
        for idx, session in enumerate(pipeline_sessions):
            session_id = session.get('id')
            if not session_id:
                continue
            
            project_name = session.get('project_name', 'Unknown')
            pipeline_id = session.get('pipeline_id', 'Unknown')
            status_icon = "🔴" if session.get("status") == "active" else "✅"
            
            button_key = f"pipeline_{session_id}_{idx}"
            button_label = f"{status_icon} {project_name}#{pipeline_id}"
            
            is_active = st.session_state.selected_session_id == session_id
            
            if st.button(
                button_label, 
                key=button_key, 
                use_container_width=True,
                type="primary" if is_active else "secondary"
            ):
                st.session_state.selected_session_id = session_id
                st.rerun()
    
    # Main Content - Active Conversation
    with main_col:
        active_session = None
        if st.session_state.selected_session_id:
            # Find session in our data
            for s in st.session_state.sessions_data:
                if s.get('id') == st.session_state.selected_session_id and s.get("session_type", "pipeline") == "pipeline":
                    active_session = s
                    break
        
        if active_session:
            session_id = active_session['id']
            project_name = active_session.get('project_name', 'Unknown')
            pipeline_id = active_session.get('pipeline_id', 'Unknown')
            
            st.subheader(f"Pipeline {pipeline_id} - {project_name}")
            
            # Pipeline info
            info_cols = st.columns(4)
            with info_cols[0]:
                st.caption(f"**Branch:** {active_session.get('branch', 'N/A')}")
            with info_cols[1]:
                st.caption(f"**Source:** {active_session.get('pipeline_source', 'N/A')}")
            with info_cols[2]:
                if failed_jobs := active_session.get('all_failed_jobs', []):
                    if len(failed_jobs) > 1:
                        st.caption(f"**Failed Jobs:** {', '.join([j['name'] for j in failed_jobs])}")
                    else:
                        st.caption(f"**Job:** {active_session.get('job_name', 'N/A')}")
            with info_cols[3]:
                if url := active_session.get('pipeline_url'):
                    st.caption(f"[View in GitLab →]({url})")
            
            st.divider()
            
            # Chat container
            render_conversation(active_session, session_id)
        else:
            st.info("👈 Select a pipeline failure from the left sidebar")
    
    # Right Sidebar - Context Panel
    with details_col:
        if active_session:
            st.subheader("📊 Pipeline Details")
            
            # Status metrics
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Status", active_session.get("status", "Unknown").title())
            with col2:
                st.metric("Stage", active_session.get("failed_stage", "N/A"))
            
            st.metric("Error Type", active_session.get("error_type", "N/A").replace("_", " ").title())
            
            # Session info
            st.divider()
            st.subheader("⏱️ Session Info")
            created = active_session.get("created_at", datetime.now().isoformat())
            st.text(f"Duration: {calculate_duration(created)}")

# Quality Issues Tab
with tab2:
    # Filter sessions by type
    quality_sessions = [s for s in st.session_state.sessions_data if s.get("session_type") == "quality"]
    
    # Main layout
    sidebar_col, main_col, details_col = st.columns([2, 5, 2])
    
    # Left Sidebar - Quality Sessions
    with sidebar_col:
        st.subheader("📊 Quality Sessions")
        
        if st.button("🔄 Refresh List", key="refresh_quality_btn", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        
        st.divider()
        
        # Display quality sessions
        for idx, session in enumerate(quality_sessions):
            session_id = session.get('id')
            if not session_id:
                continue
            
            project_name = session.get('project_name', 'Unknown')
            gate_status = session.get('quality_gate_status', 'ERROR')
            total_issues = session.get('total_issues', 0)
            
            status_icon = "🚨" if gate_status == "ERROR" else "⚠️"
            
            button_key = f"quality_{session_id}_{idx}"
            button_label = f"{status_icon} {project_name} ({total_issues} issues)"
            
            is_active = st.session_state.selected_session_id == session_id
            
            if st.button(
                button_label, 
                key=button_key, 
                use_container_width=True,
                type="primary" if is_active else "secondary"
            ):
                st.session_state.selected_session_id = session_id
                st.rerun()
    
    # Main Content - Quality Dashboard or Conversation
    with main_col:
        active_session = None
        if st.session_state.selected_session_id:
            # Find session in our data
            for s in st.session_state.sessions_data:
                if s.get('id') == st.session_state.selected_session_id and s.get("session_type") == "quality":
                    active_session = s
                    break
        
        if active_session:
            session_id = active_session['id']
            project_name = active_session.get('project_name', 'Unknown')
            
            st.subheader(f"Quality Analysis - {project_name}")
            
            # Quality summary
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Quality Gate", active_session.get('quality_gate_status', 'ERROR'), delta_color="inverse")
            with col2:
                st.metric("Total Issues", active_session.get('total_issues', 0))
            with col3:
                st.metric("Critical Issues", active_session.get('critical_issues', 0))
            
            st.divider()
            
            # Chat container
            render_conversation(active_session, session_id, quality_mode=True)
        else:
            st.info("👈 Select a quality session from the left sidebar")
    
    # Right Sidebar - Quality Details
    with details_col:
        if active_session:
            st.subheader("📊 Quality Details")
            
            st.metric("Bugs", active_session.get("bugs_count", 0))
            st.metric("Vulnerabilities", active_session.get("vulnerabilities_count", 0))
            st.metric("Code Smells", active_session.get("code_smells_count", 0))
            
            st.divider()
            st.subheader("⏱️ Session Info")
            created = active_session.get("created_at", datetime.now().isoformat())
            st.text(f"Duration: {calculate_duration(created)}")

if __name__ == "__main__":
    pass