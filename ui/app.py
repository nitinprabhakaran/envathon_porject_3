import streamlit as st
import asyncio
from datetime import datetime
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

# Custom CSS for Teams-like interface
st.markdown("""
<style>
    .pipeline-tab {
        padding: 10px 15px;
        margin: 0 5px;
        border-radius: 5px;
        cursor: pointer;
        background-color: #f0f0f0;
        border: 1px solid #ddd;
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
    .card-container {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 15px;
        margin: 10px 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .chat-message {
        padding: 10px;
        margin: 5px 0;
        border-radius: 8px;
    }
    .user-message {
        background-color: #e3f2fd;
        text-align: right;
    }
    .assistant-message {
        background-color: #f5f5f5;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "pipeline_tabs" not in st.session_state:
    st.session_state.pipeline_tabs = PipelineTabs()
if "api_client" not in st.session_state:
    st.session_state.api_client = APIClient()

async def main():
    # Header
    col1, col2, col3 = st.columns([3, 2, 1])
    with col1:
        st.title("🔧 CI/CD Failure Assistant")
    with col2:
        st.empty()
    with col3:
        if st.button("🔄 Refresh"):
            st.rerun()

    # Main layout
    sidebar_col, main_col, details_col = st.columns([1, 3, 1])

    # Left Sidebar - Pipeline List
    with sidebar_col:
        st.subheader("📋 Pipeline Failures")
        
        # Get active sessions
        sessions = await st.session_state.api_client.get_active_sessions()
        
        for session in sessions:
            status_icon = "🔴" if session["status"] == "active" else "✅"
            unread = session.get("unread_count", 0)
            badge = f"({unread})" if unread > 0 else ""
            
            if st.button(
                f"{status_icon} {session['project_id']}#{session['pipeline_id']} {badge}",
                key=f"pipeline_{session['id']}",
                use_container_width=True
            ):
                st.session_state.pipeline_tabs.set_active(session['id'])
                await load_session(session['id'])

    # Main Content - Active Conversation
    with main_col:
        active_session = st.session_state.pipeline_tabs.get_active()
        
        if active_session:
            st.subheader(f"Pipeline {active_session['pipeline_id']} - {active_session['project_id']}")
            
            # Conversation history
            chat_container = st.container()
            with chat_container:
                for msg in active_session.get("conversation_history", []):
                    if msg["role"] == "user":
                        st.markdown(
                            f'<div class="chat-message user-message">{msg["content"]}</div>',
                            unsafe_allow_html=True
                        )
                    elif msg["role"] == "assistant":
                        # Render cards if present
                        if "cards" in msg:
                            for card in msg["cards"]:
                                render_card(card)
                        else:
                            st.markdown(
                                f'<div class="chat-message assistant-message">{msg["content"]}</div>',
                                unsafe_allow_html=True
                            )
            
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
                    await send_message(active_session['id'], user_input)
        else:
            st.info("Select a pipeline failure from the left sidebar to start analyzing")

    # Right Sidebar - Context Panel
    with details_col:
        if active_session:
            st.subheader("📊 Pipeline Details")
            
            st.metric("Status", active_session.get("status", "Unknown"))
            st.metric("Failed Stage", active_session.get("failed_stage", "N/A"))
            st.metric("Error Type", active_session.get("error_type", "N/A"))
            
            st.divider()
            
            st.subheader("⏱️ Session Info")
            created = datetime.fromisoformat(active_session.get("created_at", datetime.now().isoformat()))
            st.text(f"Started: {created.strftime('%H:%M')}")
            st.text(f"Duration: {calculate_duration(created)}")
            
            st.divider()
            
            st.subheader("🛠️ Applied Fixes")
            fixes = active_session.get("applied_fixes", [])
            if fixes:
                for fix in fixes:
                    st.success(f"✓ {fix.get('type', 'Fix')}")
            else:
                st.text("No fixes applied yet")

async def load_session(session_id: str):
    """Load session data from API"""
    session_data = await st.session_state.api_client.get_session(session_id)
    st.session_state.pipeline_tabs.update_session(session_id, session_data)

async def send_message(session_id: str, message: str):
    """Send a message to the agent"""
    with st.spinner("Analyzing..."):
        response = await st.session_state.api_client.send_message(session_id, message)
        
        # Update local state
        active_session = st.session_state.pipeline_tabs.get_active()
        active_session["conversation_history"].append({
            "role": "user",
            "content": message,
            "timestamp": datetime.utcnow().isoformat()
        })
        active_session["conversation_history"].append({
            "role": "assistant",
            "content": response.get("response", ""),
            "cards": response.get("cards", []),
            "timestamp": datetime.utcnow().isoformat()
        })
        
        st.rerun()

def calculate_duration(start_time: datetime) -> str:
    """Calculate duration from start time"""
    duration = datetime.utcnow() - start_time
    hours = duration.seconds // 3600
    minutes = (duration.seconds % 3600) // 60
    return f"{hours}h {minutes}m"

# Run the app
if __name__ == "__main__":
    asyncio.run(main())