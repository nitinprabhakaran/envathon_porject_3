"""Quality issues page"""
import streamlit as st
import asyncio
from datetime import datetime
from utils.api_client import APIClient
from utils.logger import setup_logger

log = setup_logger()

# Page config
st.set_page_config(
    page_title="Quality Issues - CI/CD Assistant",
    page_icon="📊",
    layout="wide"
)

# Initialize session state
if "api_client" not in st.session_state:
    st.session_state.api_client = APIClient()
if "selected_quality_session" not in st.session_state:
    st.session_state.selected_quality_session = None
if "quality_messages" not in st.session_state:
    st.session_state.quality_messages = {}

# Header
st.title("📊 Quality Issues")

# Create layout
col1, col2 = st.columns([1, 3])

# Sidebar - Session list
with col1:
    st.subheader("Active Sessions")
    
    if st.button("🔄 Refresh", key="refresh_quality"):
        st.rerun()
    
    # Fetch sessions
    async def fetch_sessions():
        return await st.session_state.api_client.get_active_sessions()
    
    try:
        sessions = asyncio.run(fetch_sessions())
        quality_sessions = [s for s in sessions if s.get("session_type") == "quality"]
        
        if not quality_sessions:
            st.info("No active quality sessions")
        else:
            for session in quality_sessions:
                session_id = session["id"]
                project_name = session.get("project_name", "Unknown")
                gate_status = session.get("quality_gate_status", "ERROR")
                
                # Session button
                button_label = f"🚨 {project_name} - {gate_status}"
                
                if st.button(button_label, key=f"session_{session_id}", use_container_width=True):
                    st.session_state.selected_quality_session = session_id
                    log.info(f"Selected quality session: {session_id}")
                    st.rerun()
                
    except Exception as e:
        st.error(f"Failed to load sessions: {e}")
        log.error(f"Failed to load sessions: {e}")

# Main content
with col2:
    if st.session_state.selected_quality_session:
        session_id = st.session_state.selected_quality_session
        
        try:
            # Load session details
            session = asyncio.run(st.session_state.api_client.get_session(session_id))
            
            # Ensure conversation_history is properly parsed
            if isinstance(session.get("conversation_history"), str):
                import json
                session["conversation_history"] = json.loads(session["conversation_history"])
            
            # Load conversation history
            if session_id not in st.session_state.quality_messages:
                st.session_state.quality_messages[session_id] = session.get("conversation_history", [])

            # Session header
            st.subheader(f"Quality Analysis - {session.get('project_name')}")
            
            # Quality metrics
            metric_cols = st.columns(4)
            with metric_cols[0]:
                st.metric("Quality Gate", session.get("quality_gate_status", "ERROR"))
            with metric_cols[1]:
                st.metric("Total Issues", session.get("total_issues", "N/A"))
            with metric_cols[2]:
                st.metric("Critical Issues", session.get("critical_issues", "N/A"))
            with metric_cols[3]:
                st.metric("Major Issues", session.get("major_issues", "N/A"))
            
            st.divider()
            
            # Load conversation history
            if session_id not in st.session_state.quality_messages:
                st.session_state.quality_messages[session_id] = session.get("conversation_history", [])
            
            # Display conversation
            messages = st.session_state.quality_messages[session_id]
            
            # Create a container for messages
            message_container = st.container(height=500)
            
            with message_container:
                for msg in messages:
                    if msg["role"] == "system":
                        continue
                    
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])
            
            # Check if MR was created
            has_mr = any(
                "merge_request" in str(msg.get("content", "")).lower() and 
                "created" in str(msg.get("content", "")).lower() 
                for msg in messages if msg["role"] == "assistant"
            )
            
            # Action buttons
            action_cols = st.columns([3, 1, 1])
            
            with action_cols[1]:
                if not has_mr and st.button("🔀 Create MR", key="create_quality_mr", use_container_width=True):
                    log.info(f"Creating MR for quality session {session_id}")
                    with st.spinner("Creating merge request..."):
                        try:
                            response = asyncio.run(
                                st.session_state.api_client.send_message(
                                    session_id,
                                    "Create a merge request with all the quality fixes we discussed"
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
            if prompt := st.chat_input("Ask about the quality issues...", key="quality_chat"):
                log.info(f"Sending message to quality session {session_id}: {prompt[:50]}...")
                
                # Add user message
                st.session_state.quality_messages[session_id].append({
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
            log.error(f"Failed to load quality session {session_id}: {e}")
    else:
        st.info("👈 Select a quality session from the left to begin")
        
        # Show instructions
        st.markdown("""
        ### How it works:
        1. **SonarQube webhook** notifies about quality gate failures
        2. **AI analyzes** all issues (bugs, vulnerabilities, code smells)
        3. **Get fixes** with complete code changes
        4. **Create MR** with all fixes when ready
        5. **Track improvement** in code quality
        """)