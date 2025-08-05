"""Quality issues page"""
import streamlit as st
import asyncio
import json
import time
from datetime import datetime, timedelta
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

def calculate_time_remaining(expires_at):
    """Calculate time remaining until session expires"""
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
    
    now = datetime.utcnow()
    if expires_at.tzinfo:
        expires_at = expires_at.replace(tzinfo=None)
    
    remaining = expires_at - now
    
    if remaining.total_seconds() <= 0:
        return "Expired"
    
    hours = int(remaining.total_seconds() // 3600)
    minutes = int((remaining.total_seconds() % 3600) // 60)
    
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"

# Header
st.title("📊 Quality Issues")

# Top navigation bar
col_nav1, col_nav2, col_nav3 = st.columns([2, 2, 1])
with col_nav1:
    date_range = st.date_input(
        "Date Range",
        value=(datetime.now() - timedelta(days=7), datetime.now()),
        key="quality_date_range"
    )
with col_nav2:
    severity_filter = st.multiselect(
        "Severity Filter",
        ["Critical", "Major", "Minor"],
        default=["Critical", "Major"],
        key="severity_filter"
    )
with col_nav3:
    if st.button("🔄 Refresh", key="refresh_quality_main"):
        st.rerun()

# Main layout - adjusted column widths
col1, col2, col3 = st.columns([1.5, 3, 1.5])

# Column 1: Session list
with col1:
    st.subheader("Projects")
    
    # Fetch sessions and group by project
    async def fetch_and_group_sessions():
        sessions = await st.session_state.api_client.get_active_sessions()
        quality_sessions = [s for s in sessions if s.get("session_type") == "quality"]
        
        # Group by project
        groups = {}
        for session in quality_sessions:
            project = session.get("project_name", "Unknown")
            
            if project not in groups:
                groups[project] = []
            
            groups[project].append(session)
        
        return groups
    
    try:
        failure_groups = asyncio.run(fetch_and_group_sessions())
        
        if not failure_groups:
            st.info("No active quality sessions")
        else:
            # Project expandables
            for project_name, sessions in failure_groups.items():
                # Count active issues
                active_count = sum(1 for s in sessions if s.get("status") == "active")
                total_issues = sum(s.get("total_issues", 0) for s in sessions)
                icon = "🔴" if active_count > 0 else "🟢"
                
                with st.expander(f"{icon} {project_name} ({total_issues} issues)", expanded=active_count > 0):
                    for session in sessions:
                        session_id = session["id"]
                        time_remaining = calculate_time_remaining(session.get('expires_at'))
                        fix_attempts = session.get("webhook_data", {}).get("fix_attempts", [])
                        
                        # Color code based on fix status
                        if fix_attempts:
                            if any(att.get("status") == "success" for att in fix_attempts):
                                status_color = "🟢"
                            elif any(att.get("status") == "pending" for att in fix_attempts):
                                status_color = "🟡"
                            else:
                                status_color = "🔴"
                        else:
                            # Color code based on time remaining
                            if time_remaining == "Expired":
                                status_color = "🔴"
                            elif "m" in time_remaining and not "h" in time_remaining:
                                status_color = "🟡"
                            else:
                                status_color = "🟢"
                        
                        # Session button
                        button_label = f"{status_color} Quality Gate Failed\n{session.get('total_issues', 0)} issues\n⏰ {time_remaining}"
                        if fix_attempts:
                            button_label += f"\n🔄 {len(fix_attempts)} fix(es)"
                        
                        if st.button(
                            button_label,
                            key=f"quality_{session_id}",
                            use_container_width=True
                        ):
                            st.session_state.selected_quality_session = session
                            st.rerun()
    
    except Exception as e:
        st.error(f"Failed to load projects: {e}")

# Column 2: Main Content Area (Analysis & Chat)
with col2:
    if st.session_state.selected_quality_session:
        session = st.session_state.selected_quality_session
        session_id = session["id"]
        
        st.subheader("Quality Analysis")
        
        # Load full session data
        try:
            full_session = asyncio.run(st.session_state.api_client.get_session(session_id))
            messages = full_session.get("conversation_history", [])
            fix_attempts = full_session.get("webhook_data", {}).get("fix_attempts", [])
            
            # Show expiration timer at top
            time_remaining = calculate_time_remaining(full_session.get('expires_at'))
            if time_remaining == "Expired":
                st.error(f"⏰ This session has expired and will be cleaned up")
            elif "m" in time_remaining and not "h" in time_remaining:
                st.warning(f"⏰ Session expires in: {time_remaining}")
            else:
                st.info(f"⏰ Session expires in: {time_remaining}")
            
            # Show fix iteration info if applicable
            if fix_attempts:
                col_iter1, col_iter2 = st.columns([3, 1])
                with col_iter1:
                    # Check if any attempts are pending
                    pending_attempts = [att for att in fix_attempts if att.get("status") == "pending"]
                    successful_attempts = [att for att in fix_attempts if att.get("status") == "success"]
                    
                    if successful_attempts:
                        st.success(f"✅ Fix Iterations: {len(fix_attempts)}/5 ({len(successful_attempts)} successful)")
                    elif pending_attempts:
                        st.warning(f"🔄 Fix Iterations: {len(fix_attempts)}/5 (Checking status...)")
                        # Auto-refresh every 5 seconds if there are pending fixes
                        time.sleep(5)
                        st.rerun()
                    else:
                        st.error(f"❌ Fix Iterations: {len(fix_attempts)}/5 (all failed)")
                
                with col_iter2:
                    with st.expander("Fix History"):
                        for i, attempt in enumerate(fix_attempts):
                            status_icon = "✅" if attempt.get("status") == "success" else "❌" if attempt.get("status") == "failed" else "⏳"
                            st.text(f"{status_icon} Attempt {i+1}: MR #{attempt['mr_id']}")
                            st.caption(f"Branch: {attempt['branch']}")
                            st.caption(f"Status: {attempt.get('status', 'pending')}")
            
            # Quality metrics summary cards
            col_m1, col_m2, col_m3 = st.columns(3)
            
            with col_m1:
                st.metric("🐛 Bugs", full_session.get("bug_count", 0))
            with col_m2:
                st.metric("🔒 Vulnerabilities", full_session.get("vulnerability_count", 0))
            with col_m3:
                st.metric("💩 Code Smells", full_session.get("code_smell_count", 0))
            
            # Action buttons
            col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
            
            mr_url = full_session.get("merge_request_url")
            
            with col_btn1:
                # Check if current branch is a fix branch created by our system
                current_branch = full_session.get("branch", "")
                is_fix_branch = current_branch.startswith("fix/sonarqube_")
                
                # Check fix status
                all_successful = all(att.get("status") == "success" for att in fix_attempts) if fix_attempts else False
                
                if all_successful and mr_url:
                    st.success("✅ Fix Applied Successfully!")
                    st.link_button("📄 View MR", mr_url, use_container_width=True, type="primary")
                elif len(fix_attempts) >= 5:
                    st.error("❌ Max attempts reached")
                elif is_fix_branch and not mr_url:
                    # This is analyzing a failure on OUR fix branch - show Apply Fix
                    if st.button("🔧 Apply Fix", use_container_width=True):
                        with st.spinner("Applying fix to the existing branch..."):
                            response = asyncio.run(
                                st.session_state.api_client.send_message(
                                    session_id, 
                                    "Apply the fixes to the current feature branch. This is an iteration on our existing fix branch, so update the same branch with additional commits."
                                )
                            )
                            if response.get("merge_request_url"):
                                st.success(f"✅ Fix applied to existing MR")
                            st.rerun()
                elif len(fix_attempts) > 0 and not mr_url:
                    # Show retry button for subsequent attempts
                    if st.button("🔄 Try Another Fix", use_container_width=True):
                        with st.spinner("Analyzing latest quality issues and creating additional fixes..."):
                            response = asyncio.run(
                                st.session_state.api_client.send_message(
                                    session_id, 
                                    "The quality gate is still failing. Please analyze the latest quality issues and create another fix targeting any remaining problems."
                                )
                            )
                            if response.get("merge_request_url"):
                                st.success(f"✅ Additional fixes added to MR")
                            st.rerun()
                elif not mr_url:
                    # First attempt - create MR button
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
                if st.button("💬 Ask Question", use_container_width=True):
                    st.session_state.show_quality_chat[session_id] = not st.session_state.show_quality_chat.get(session_id, False)
            
            st.divider()
            
            # Always show conversation history
            st.markdown("### 📋 Analysis & Discussion")
            
            # Create a container for messages with fixed height and scroll
            message_container = st.container(height=1400)
            
            with message_container:
                for msg in messages:
                    if msg["role"] != "system":
                        with st.chat_message(msg["role"]):
                            content = msg.get("content", "")

                            # Try to parse JSON string if it looks like JSON
                            if isinstance(content, str) and content.strip().startswith('{'):
                                try:
                                    parsed = json.loads(content)
                                    if isinstance(parsed, dict):
                                        if "text" in parsed:
                                            content = parsed["text"]
                                        elif "message" in parsed:
                                            content = parsed["message"]
                                        elif "content" in parsed:
                                            if isinstance(parsed["content"], list):
                                                content = parsed["content"][0].get("text", str(parsed))
                                            else:
                                                content = parsed["content"]
                                except json.JSONDecodeError:
                                    pass
                                    
                            st.markdown(content)
            
            # Chat input interface (only shown when chat button is clicked)
            if st.session_state.show_quality_chat.get(session_id):
                st.divider()
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
            st.error(f"Failed to load session details: {e}")
    
    else:
        # Show quality cards when no session is selected
        st.subheader("Quality Analysis")
        
        if failure_groups:
            for project_name, sessions in failure_groups.items():
                st.markdown(f"### 📊 {project_name}")
                
                for session in sessions:
                    status = session.get("status", "active")
                    time_remaining = calculate_time_remaining(session.get('expires_at'))
                    fix_attempts = session.get("webhook_data", {}).get("fix_attempts", [])
                    
                    # Determine actual status based on fix attempts
                    if fix_attempts:
                        # Check if any fix is successful
                        successful_fixes = [att for att in fix_attempts if att.get("status") == "success"]
                        pending_fixes = [att for att in fix_attempts if att.get("status") == "pending"]
                        
                        if successful_fixes:
                            display_status = "fixed"
                            status_emoji = "🟢"
                            status_text = "Fixed"
                        elif pending_fixes:
                            display_status = "fixing"
                            status_emoji = "🟡"
                            status_text = "Fixing..."
                        else:
                            display_status = "failed"
                            status_emoji = "🔴"
                            status_text = f"Failed ({len(fix_attempts)} attempts)"
                    else:
                        display_status = status
                        status_emoji = "🔴" if status == "active" else "🟢" if status == "resolved" else "🟡"
                        status_text = "Active" if status == "active" else "Fixed" if status == "resolved" else "Analyzing"
                    
                    # Create card with proper coloring
                    with st.container():
                        col_info, col_action = st.columns([4, 1])
                        
                        with col_info:
                            # Time color based on remaining time
                            if time_remaining == "Expired":
                                time_emoji = "🔴"
                            elif "m" in time_remaining and not "h" in time_remaining:
                                time_emoji = "🟡"
                            else:
                                time_emoji = "🟢"
                            
                            # Use colored text based on status
                            if display_status == "fixed":
                                st.markdown(f"""
                                **{status_emoji} Quality Gate** - :green[{status_text}]
                                
                                Issues: {session.get('total_issues', 0)} | 
                                Bugs: {session.get('bug_count', 0)} | 
                                Vulnerabilities: {session.get('vulnerability_count', 0)} |
                                Fixes: {len(fix_attempts)} |
                                Last: {datetime.fromisoformat(session.get("created_at", datetime.now().isoformat())).strftime("%b %d, %H:%M")} |
                                {time_emoji} Expires: {time_remaining}
                                """)
                            elif display_status == "fixing":
                                st.markdown(f"""
                                **{status_emoji} Quality Gate** - :orange[{status_text}]
                                
                                Issues: {session.get('total_issues', 0)} | 
                                Bugs: {session.get('bug_count', 0)} | 
                                Vulnerabilities: {session.get('vulnerability_count', 0)} |
                                Fixes: {len(fix_attempts)} |
                                Last: {datetime.fromisoformat(session.get("created_at", datetime.now().isoformat())).strftime("%b %d, %H:%M")} |
                                {time_emoji} Expires: {time_remaining}
                                """)
                            else:
                                st.markdown(f"""
                                **{status_emoji} Quality Gate** - :red[{status_text}]
                                
                                Issues: {session.get('total_issues', 0)} | 
                                Bugs: {session.get('bug_count', 0)} | 
                                Vulnerabilities: {session.get('vulnerability_count', 0)} |
                                Fixes: {len(fix_attempts)} |
                                Last: {datetime.fromisoformat(session.get("created_at", datetime.now().isoformat())).strftime("%b %d, %H:%M")} |
                                {time_emoji} Expires: {time_remaining}
                                """)
                        
                        with col_action:
                            if st.button("View", key=f"view_{session['id']}"):
                                st.session_state.selected_quality_session = session
                                st.rerun()
                    
                    st.divider()
                    
            # Auto-refresh check for pending fixes
            has_pending = False
            for project_name, sessions in failure_groups.items():
                for session in sessions:
                    fix_attempts = session.get("webhook_data", {}).get("fix_attempts", [])
                    if any(att.get("status") == "pending" for att in fix_attempts):
                        has_pending = True
                        break
                if has_pending:
                    break
            
            if has_pending:
                # Auto-refresh every 5 seconds
                time.sleep(5)
                st.rerun()
        else:
            st.info("Select a project from the left to view quality issues")
            
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
        session = st.session_state.selected_quality_session
        
        st.subheader("Quality Metrics")
        
        # Quality metrics
        st.markdown("**Issue Breakdown:**")
        st.caption(f"🐛 Bugs: {session.get('bug_count', 0)}")
        st.caption(f"🔒 Vulnerabilities: {session.get('vulnerability_count', 0)}")
        st.caption(f"💩 Code Smells: {session.get('code_smell_count', 0)}")
        
        # Quality ratings
        st.markdown("**Quality Ratings:**")
        st.caption(f"Reliability: {session.get('reliability_rating', '?')}")
        st.caption(f"Security: {session.get('security_rating', '?')}")
        st.caption(f"Maintainability: {session.get('maintainability_rating', '?')}")
        
        # Fix attempts info
        fix_attempts = session.get("webhook_data", {}).get("fix_attempts", [])
        if fix_attempts:
            st.markdown("**Fix Information:**")
            st.caption(f"Iterations: {len(fix_attempts)}/5")
            
            successful = [att for att in fix_attempts if att.get("status") == "success"]
            if successful:
                st.success(f"✅ {len(successful)} successful fix(es)")
            
            st.caption(f"Current Branch: {fix_attempts[-1]['branch']}")
        
        # Session timing
        st.markdown("**Session Info:**")
        created_at = session.get('created_at')
        if created_at:
            created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            st.caption(f"Created: {created_time.strftime('%b %d, %H:%M')}")
        
        time_remaining = calculate_time_remaining(session.get('expires_at'))
        if time_remaining == "Expired":
            st.caption("⏰ Status: Expired")
        else:
            st.caption(f"⏰ Expires in: {time_remaining}")
        
        # Link to SonarQube
        if st.button("View in SonarQube", use_container_width=True):
            st.write("SonarQube dashboard link would open here")