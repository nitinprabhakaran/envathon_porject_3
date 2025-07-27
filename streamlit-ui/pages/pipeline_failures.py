"""Pipeline failures page"""
import streamlit as st
import asyncio
from datetime import datetime
from utils.api_client import APIClient
from utils.logger import setup_logger

log = setup_logger()

# Page config
st.set_page_config(
    page_title="Pipeline Failures - CI/CD Assistant",
    page_icon="🚀",
    layout="wide"
)

# Initialize session state
if "api_client" not in st.session_state:
    st.session_state.api_client = APIClient()
if "selected_pipeline_session" not in st.session_state:
    st.session_state.selected_pipeline_session = None
if "pipeline_messages" not in st.session_state:
    st.session_state.pipeline_messages = {}

# Header
st.title("🚀 Pipeline Failures")

# Create layout
col1, col2 = st.columns([1, 3])

# Sidebar - Session list
with col1:
    st.subheader("Active Sessions")
    
    if st.button("🔄 Refresh", key="refresh_pipeline"):
        st.rerun()
    
    # Fetch sessions
    async def fetch_sessions():
        return await st.session_state.api_client.get_active_sessions()
    
    try:
        sessions = asyncio.run(fetch_sessions())
        pipeline_sessions = [s for s in sessions if s.get("session_type") == "pipeline"]
        
        if not pipeline_sessions:
            st.info("No active pipeline sessions")
        else:
            for session in pipeline_sessions:
                session_id = session["id"]
                project_name = session.get("project_name", "Unknown")
                pipeline_id = session.get("pipeline_id", "N/A")
                status = session.get("status", "active")
                
                # Session button
                button_label = f"{'🔴' if status == 'active' else '✅'} {project_name} #{pipeline_id}"
                
                if st.button(button_label, key=f"session_{session_id}", use_container_width=True):
                    st.session_state.selected_pipeline_session = session_id
                    log.info(f"Selected pipeline session: {session_id}")
                    st.rerun()
                
    except Exception as e:
        st.error(f"Failed to load sessions: {e}")
        log.error(f"Failed to load sessions: {e}")

# Main content
with col2:
    if st.session_state.selected_pipeline_session:
        session_id = st.session_state.selected_pipeline_session
        
        try:
            # Load session details
            session = asyncio.run(st.session_state.api_client.get_session(session_id))
            
            # Session header
            st.subheader(f"Pipeline {session.get('pipeline_id')} - {session.get('project_name')}")
            
            # Metadata
            meta_cols = st.columns(4)
            with meta_cols[0]:
                st.caption(f"**Branch:** {session.get('branch', 'N/A')}")
            with meta_cols[1]:
                st.caption(f"**Stage:** {session.get('failed_stage', 'N/A')}")
            with meta_cols[2]:
                st.caption(f"**Job:** {session.get('job_name', 'N/A')}")
            with meta_cols[3]:
                if url := session.get('pipeline_url'):
                    st.link_button("View in GitLab", url)
            
            st.divider()
            
            # Load conversation history
            if session_id not in st.session_state.pipeline_messages:
                st.session_state.pipeline_messages[session_id] = session.get("conversation_history", [])
            
            # Display conversation
            messages = st.session_state.pipeline_messages[session_id]
            
            # Create a container for messages
            message_container = st.container(height=500)
            
            with message_container:
                for msg in messages:
                    if msg["role"] == "system":
                        continue
                    
                    with st.chat_message(msg["role"]):
                        content = msg.get("content", "")
                        if isinstance(content, dict):
                            content = content.get("message", str(content))
                        st.markdown(content)
            
            # Check if MR was created
            has_mr = any("merge_request" in msg.get("content", "").lower() and "created" in msg.get("content", "").lower() 
                        for msg in messages if msg["role"] == "assistant")
            
            # Action buttons
            action_cols = st.columns([3, 1, 1])
            
            with action_cols[1]:
                if not has_mr and st.button("🔀 Create MR", key="create_mr_btn", use_container_width=True):
                    log.info(f"Creating MR for session {session_id}")
                    with st.spinner("Creating merge request..."):
                        try:
                            response = asyncio.run(
                                st.session_state.api_client.send_message(
                                    session_id,
                                    "Create a merge request with all the fixes we discussed"
                                )
                            )
                            response_content = response.get("response", "")
                            if isinstance(response_content, dict):
                                response_content = response_content.get("message", str(response_content))
                            
                            # Add response to messages
                            st.session_state.pipeline_messages[session_id].append({
                                "role": "assistant",
                                "content": response_content,
                                "timestamp": datetime.utcnow().isoformat()
                            })
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to create MR: {e}")
                            log.error(f"Failed to create MR: {e}")
            
            with action_cols[2]:
                if session.get("merge_request_url"):
                    st.link_button("View MR", session["merge_request_url"])
            
            # Chat input
            if prompt := st.chat_input("Ask about the failure...", key="pipeline_chat"):
                log.info(f"Sending message to session {session_id}: {prompt[:50]}...")
                
                # Add user message
                st.session_state.pipeline_messages[session_id].append({
                    "role": "user",
                    "content": prompt,
                    "timestamp": datetime.utcnow().isoformat()
                })
                
                # Send to API
                with st.spinner("Analyzing..."):
                    try:
                        response = asyncio.run(
                            st.session_state.api_client.send_message(session_id, prompt)
                        )
                        
                        response_content = response.get("response", "")
                        if isinstance(response_content, dict):
                            response_content = response_content.get("message", str(response_content))
                            
                        # Add response to messages
                        st.session_state.pipeline_messages[session_id].append({
                            "role": "assistant",
                            "content": response_content,
                            "timestamp": datetime.utcnow().isoformat()
                        })
                        
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Failed to send message: {e}")
                        log.error(f"Failed to send message: {e}")
        
        except Exception as e:
            st.error(f"Failed to load session: {e}")
            log.error(f"Failed to load session {session_id}: {e}")
    else:
        st.info("👈 Select a pipeline session from the left to begin")
        
        # Show instructions
        st.markdown("""
        ### How it works:
        1. **GitLab webhook** notifies about pipeline failures
        2. **AI analyzes** logs and identifies root cause
        3. **Get solutions** with confidence scores
        4. **Create MR** with fixes when ready
        5. **Track progress** until resolved
        """)