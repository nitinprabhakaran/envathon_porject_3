"""Quality issues page"""
import streamlit as st
import asyncio
import json
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
if "show_quality_chat" not in st.session_state:
    st.session_state.show_quality_chat = {}

# Header
st.title("📊 Quality Issues")

# Create layout - adjusted column widths
col1, col2, col3 = st.columns([1.5, 3, 1.5])

# Column 1: Session list
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
        
        # Remove duplicates based on project_name (keep latest)
        seen_projects = {}
        for session in quality_sessions:
            project_name = session.get("project_name", "Unknown")
            if project_name not in seen_projects or session.get("created_at", "") > seen_projects[project_name].get("created_at", ""):
                seen_projects[project_name] = session
        
        quality_sessions = list(seen_projects.values())
        
        if not quality_sessions:
            st.info("No active quality sessions")
        else:
            for session in quality_sessions:
                session_id = session["id"]
                project_name = session.get("project_name", "Unknown")
                gate_status = session.get("quality_gate_status", "ERROR")
                total_issues = session.get("total_issues", 0)
                
                # Session button
                button_label = f"🚨 {project_name}\n{total_issues} issues"
                
                if st.button(button_label, key=f"session_{session_id}", use_container_width=True):
                    st.session_state.selected_quality_session = session_id
                    log.info(f"Selected quality session: {session_id}")
                    st.rerun()
                
    except Exception as e:
        st.error(f"Failed to load sessions: {e}")

# Column 2: Main Content Area (Analysis & Chat)
with col2:
    if st.session_state.selected_quality_session:
        session_id = st.session_state.selected_quality_session
        
        try:
            # Load session details
            session = asyncio.run(st.session_state.api_client.get_session(session_id))
            
            # Ensure conversation_history is properly parsed
            if isinstance(session.get("conversation_history"), str):
                session["conversation_history"] = json.loads(session["conversation_history"])
            
            # Session header
            st.subheader(f"Quality Analysis - {session.get('project_name')}")
            
            # Get metrics
            metrics = session.get("webhook_data", {}).get("quality_metrics", {})
            
            # Quality metrics summary
            col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
            
            with col_m1:
                st.metric("Quality Gate", session.get("quality_gate_status", "ERROR"))
            with col_m2:
                st.metric("Total Issues", session.get("total_issues", metrics.get("total_issues", 0)))
            with col_m3:
                st.metric("Critical", session.get("critical_issues", metrics.get("critical_issues", 0)))
            with col_m4:
                st.metric("Major", session.get("major_issues", metrics.get("major_issues", 0)))
            with col_m5:
                coverage = metrics.get("coverage", session.get("coverage", "0"))
                st.metric("Coverage", f"{float(coverage or 0):.1f}%")
            
            # Issue breakdown
            st.markdown("#### Issue Breakdown")
            issue_cols = st.columns(3)
            
            with issue_cols[0]:
                bugs = metrics.get("bug_count", session.get("bug_count", 0))
                st.info(f"🐛 **Bugs**: {bugs} issues")
            with issue_cols[1]:
                vulns = metrics.get("vulnerability_count", session.get("vulnerability_count", 0))
                st.warning(f"🔒 **Vulnerabilities**: {vulns} issues")
            with issue_cols[2]:
                smells = metrics.get("code_smell_count", session.get("code_smell_count", 0))
                st.success(f"💩 **Code Smells**: {smells} issues")
            
            # Quality ratings
            st.markdown("#### Quality Ratings")
            rating_cols = st.columns(3)
            
            with rating_cols[0]:
                rel_rating = metrics.get("reliability_rating", session.get("reliability_rating", "?"))
                st.markdown(f"**Reliability**: {rel_rating}")
            with rating_cols[1]:
                sec_rating = metrics.get("security_rating", session.get("security_rating", "?"))
                st.markdown(f"**Security**: {sec_rating}")
            with rating_cols[2]:
                main_rating = metrics.get("maintainability_rating", session.get("maintainability_rating", "?"))
                st.markdown(f"**Maintainability**: {main_rating}")
            
            st.divider()
            
            # Load conversation
            messages = session.get("conversation_history", [])
            if session_id not in st.session_state.quality_messages:
                st.session_state.quality_messages[session_id] = messages
            
            # Display latest analysis
            st.markdown("### 📋 Latest Analysis")
            analysis_found = False
            for msg in reversed(messages):
                if msg["role"] == "assistant" and msg.get("content"):
                    analysis_found = True
                    with st.expander("View Full Analysis", expanded=True):
                        st.markdown(msg["content"])
                    break
            
            if not analysis_found:
                st.info("Analysis in progress... Please wait.")
            
            st.divider()
            
            # Action buttons
            col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
            
            mr_url = session.get("merge_request_url")
            
            with col_btn1:
                if not mr_url:
                    if st.button("🔀 Create MR", use_container_width=True):
                        with st.spinner("Creating merge request..."):
                            response = asyncio.run(
                                st.session_state.api_client.send_message(
                                    session_id, 
                                    "Create a merge request with all the quality fixes we discussed. Make sure to include the complete MR URL in your response."
                                )
                            )
                            if response.get("merge_request_url"):
                                st.success(f"✅ MR Created: {response['merge_request_url']}")
                            st.rerun()
                else:
                    st.link_button("📄 View MR", mr_url, use_container_width=True)
            
            with col_btn2:
                if st.button("💬 Chat", use_container_width=True):
                    st.session_state.show_quality_chat[session_id] = not st.session_state.show_quality_chat.get(session_id, False)
            
            # Chat interface
            if st.session_state.show_quality_chat.get(session_id):
                st.divider()
                st.markdown("### 💬 Chat")
                
                # Display conversation history
                for msg in messages:
                    if msg["role"] != "system":
                        with st.chat_message(msg["role"]):
                            st.write(msg.get("content", ""))
                
                # Chat input
                if prompt := st.chat_input("Ask about the quality issues..."):
                    # Add user message
                    with st.chat_message("user"):
                        st.write(prompt)
                    
                    # Get response
                    with st.chat_message("assistant"):
                        with st.spinner("Analyzing..."):
                            response = asyncio.run(
                                st.session_state.api_client.send_message(session_id, prompt)
                            )
                            response_text = response.get("response", "")
                            st.write(response_text)
                            
                            if response.get("merge_request_url"):
                                st.success(f"✅ MR Created: {response['merge_request_url']}")
                    
                    st.rerun()
        
        except Exception as e:
            st.error(f"Failed to load session: {e}")
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

# Column 3: Metadata Panel
with col3:
    if st.session_state.selected_quality_session:
        st.subheader("Project Info")
        
        # Additional project details could go here
        st.markdown("**SonarQube Details:**")
        st.caption("View detailed reports in SonarQube dashboard")