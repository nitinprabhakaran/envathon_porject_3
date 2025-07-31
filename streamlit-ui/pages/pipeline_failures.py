"""Pipeline failures page"""
import streamlit as st
import asyncio
import json
from datetime import datetime, timedelta
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
if "selected_project" not in st.session_state:
    st.session_state.selected_project = None
if "selected_failure" not in st.session_state:
    st.session_state.selected_failure = None
if "failure_groups" not in st.session_state:
    st.session_state.failure_groups = {}
if "show_chat" not in st.session_state:
    st.session_state.show_chat = {}

# Header
st.title("🚀 Pipeline Failures")

# Top navigation bar
col_nav1, col_nav2, col_nav3 = st.columns([2, 2, 1])
with col_nav1:
    date_range = st.date_input(
        "Date Range",
        value=(datetime.now() - timedelta(days=7), datetime.now()),
        key="date_range"
    )
with col_nav2:
    status_filter = st.multiselect(
        "Status Filter",
        ["Failed", "Analyzing", "Fixed"],
        default=["Failed", "Analyzing"],
        key="status_filter"
    )
with col_nav3:
    if st.button("🔄 Refresh", key="refresh_main"):
        st.rerun()

# Main layout - adjusted column widths
col1, col2, col3 = st.columns([1.5, 3, 1.5])

# Column 1: Project Navigator
with col1:
    st.subheader("Projects")
    
    # Fetch sessions and group by project
    async def fetch_and_group_sessions():
        sessions = await st.session_state.api_client.get_active_sessions()
        pipeline_sessions = [s for s in sessions if s.get("session_type") == "pipeline"]
        
        # Group by project and branch
        groups = {}
        for session in pipeline_sessions:
            project = session.get("project_name", "Unknown")
            branch = session.get("branch", "main")
            
            if project not in groups:
                groups[project] = {}
            if branch not in groups[project]:
                groups[project][branch] = []
            
            groups[project][branch].append(session)
        
        return groups
    
    try:
        st.session_state.failure_groups = asyncio.run(fetch_and_group_sessions())
        
        # Project selector
        projects = list(st.session_state.failure_groups.keys())
        if projects:
            selected_project = st.selectbox(
                "Select Project",
                projects,
                index=0 if st.session_state.selected_project is None else 
                      projects.index(st.session_state.selected_project) if st.session_state.selected_project in projects else 0,
                key="project_selector"
            )
            st.session_state.selected_project = selected_project
            
            # Branch expandables
            project_branches = st.session_state.failure_groups.get(selected_project, {})
            for branch, sessions in project_branches.items():
                # Count failures by status
                active_count = sum(1 for s in sessions if s.get("status") == "active")
                icon = "🔴" if active_count > 0 else "🟢"
                
                with st.expander(f"{icon} {branch} ({len(sessions)} issues)", expanded=active_count > 0):
                    for session in sessions:
                        # Get job name or use fallback
                        job_name = session.get('job_name') or session.get('failed_stage') or 'Unknown Job'
                        button_label = f"{job_name}"
                        
                        if st.button(
                            button_label,
                            key=f"job_{session['id']}",
                            use_container_width=True
                        ):
                            st.session_state.selected_failure = session
                            st.rerun()
    
    except Exception as e:
        st.error(f"Failed to load projects: {e}")

# Column 2: Main Content Area (Analysis & Chat)
with col2:
    if st.session_state.selected_failure:
        session = st.session_state.selected_failure
        session_id = session["id"]
        
        st.subheader("Failure Details")
        
        # Load full session data
        try:
            full_session = asyncio.run(st.session_state.api_client.get_session(session_id))
            messages = full_session.get("conversation_history", [])
            
            # Display latest analysis
            st.markdown("### 📋 Latest Analysis")
            analysis_found = False
            for msg in reversed(messages):
                if msg["role"] == "assistant" and msg.get("content"):
                    analysis_found = True
                    # Display full analysis in expandable section
                    with st.expander("View Full Analysis", expanded=True):
                        st.markdown(msg["content"])
                    break
            
            if not analysis_found:
                st.info("Analysis in progress... Please wait.")
            
            st.divider()
            
            # Action buttons
            col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
            
            mr_url = full_session.get("merge_request_url")
            
            with col_btn1:
                if not mr_url:
                    if st.button("🔀 Create MR", use_container_width=True):
                        with st.spinner("Creating merge request..."):
                            response = asyncio.run(
                                st.session_state.api_client.send_message(
                                    session_id, 
                                    "Create a merge request with all the fixes we discussed. Make sure to include the complete MR URL in your response."
                                )
                            )
                            if response.get("merge_request_url"):
                                st.success(f"✅ MR Created: {response['merge_request_url']}")
                            st.rerun()
                else:
                    st.link_button("📄 View MR", mr_url, use_container_width=True)
            
            with col_btn2:
                if st.button("💬 Chat", use_container_width=True):
                    st.session_state.show_chat[session_id] = not st.session_state.show_chat.get(session_id, False)
            
            # Chat interface
            if st.session_state.show_chat.get(session_id):
                st.divider()
                st.markdown("### 💬 Chat")
                
                # Display conversation history
                for msg in messages:
                    if msg["role"] != "system":
                        with st.chat_message(msg["role"]):
                            st.write(msg.get("content", ""))
                
                # Chat input
                if prompt := st.chat_input("Ask about this failure..."):
                    # Add user message
                    with st.chat_message("user"):
                        st.write(prompt)
                    
                    # Get response
                    with st.chat_message("assistant"):
                        with st.spinner("Thinking..."):
                            response = asyncio.run(
                                st.session_state.api_client.send_message(session_id, prompt)
                            )
                            response_text = response.get("response", "")
                            st.write(response_text)
                            
                            if response.get("merge_request_url"):
                                st.success(f"✅ MR Created: {response['merge_request_url']}")
                    
                    st.rerun()
        
        except Exception as e:
            st.error(f"Failed to load session details: {e}")
    
    else:
        # Show job cards when no failure is selected
        st.subheader("Failure Details")
        
        if st.session_state.selected_project and st.session_state.failure_groups:
            project_data = st.session_state.failure_groups.get(st.session_state.selected_project, {})
            
            for branch, sessions in project_data.items():
                st.markdown(f"### 🌿 {branch}")
                
                # Group by job name
                job_groups = {}
                for session in sessions:
                    job_name = session.get("job_name", "Unknown")
                    if job_name not in job_groups:
                        job_groups[job_name] = []
                    job_groups[job_name].append(session)
                
                # Display job cards
                for job_name, job_sessions in job_groups.items():
                    latest_session = max(job_sessions, key=lambda x: x.get("created_at", ""))
                    status = latest_session.get("status", "active")
                    
                    # Create card
                    with st.container():
                        col_info, col_action = st.columns([4, 1])
                        
                        with col_info:
                            status_emoji = "🔴" if status == "active" else "🟢" if status == "resolved" else "🟡"
                            status_text = "Failed" if status == "active" else "Fixed" if status == "resolved" else "Analyzing"
                            
                            st.markdown(f"""
                            **{status_emoji} {job_name}** - {status_text}
                            
                            Stage: {latest_session.get("failed_stage", "Unknown")} | 
                            {len(job_sessions)} occurrence(s) | 
                            Last: {datetime.fromisoformat(latest_session.get("created_at", datetime.now().isoformat())).strftime("%b %d, %H:%M")}
                            """)
                        
                        with col_action:
                            if st.button("View", key=f"view_{latest_session['id']}"):
                                st.session_state.selected_failure = latest_session
                                st.rerun()
                    
                    st.divider()
        else:
            st.info("Select a project from the left to view failures")

# Column 3: Metadata Panel
with col3:
    if st.session_state.selected_failure:
        session = st.session_state.selected_failure
        
        st.subheader("Analysis & Chat")
        
        # Session metadata
        st.markdown("**Pipeline Details:**")
        st.caption(f"Pipeline: #{session.get('pipeline_id', 'N/A')}")
        st.caption(f"Stage: {session.get('failed_stage', 'N/A')}")
        st.caption(f"Job: {session.get('job_name', 'N/A')}")
        
        if url := session.get('pipeline_url'):
            st.link_button("View in GitLab", url, use_container_width=True)