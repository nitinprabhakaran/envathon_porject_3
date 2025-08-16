"""Project Setup & Subscription Management - Self-Service Portal"""
import streamlit as st
import asyncio
from datetime import datetime, timedelta
from utils.api_client import UnifiedAPIClient
from utils.logger import setup_logger
import os

# Setup
log = setup_logger()
st.set_page_config(page_title="Project Setup", page_icon="⚙️", layout="wide")

# Initialize API client if not already done
if 'api_client' not in st.session_state:
    st.session_state.api_client = UnifiedAPIClient()

st.title("⚙️ Project Setup & Webhook Management")
st.markdown("**Self-Service Portal** - Configure automatic CI/CD failure analysis for your projects")

# Add helpful info banner
st.info("🔓 **Open Access**: Anyone can subscribe their projects for automatic failure analysis. No authentication required!")

# Check system health
def check_system_health():
    return st.session_state.api_client.health_check()

try:
    health_status = check_system_health()
    if health_status.get("strands_agent") and health_status.get("webhook_handler"):
        st.success("✅ All systems operational")
    else:
        st.warning("⚠️ Some services may be unavailable")
        if not health_status.get("strands_agent"):
            st.error("❌ Strands Agent is not responding")
        if not health_status.get("webhook_handler"):
            st.error("❌ Webhook Handler is not responding")
except Exception as e:
    st.error(f"❌ Cannot connect to backend services: {e}")

# Tabs for different functions
tab1, tab2, tab3 = st.tabs(["🚀 New Subscription", "📋 Manage Subscriptions", "📊 Webhook Status"])

with tab1:
    st.header("Create New Subscription")
    st.markdown("Set up automatic webhook monitoring for your GitLab or SonarQube project")
    
    # Project type selection
    project_type = st.selectbox(
        "Project Type",
        ["gitlab", "sonarqube"],
        format_func=lambda x: "GitLab Project" if x == "gitlab" else "SonarQube Project"
    )
    
    col1, col2 = st.columns(2)
    
    with col1:
        if project_type == "gitlab":
            project_id = st.text_input(
                "GitLab Project ID",
                help="Numeric ID of your GitLab project (found in project settings)",
                placeholder="12345"
            )
            
            project_url = st.text_input(
                "GitLab Instance URL",
                help="Base URL of your GitLab instance",
                placeholder="https://gitlab.example.com"
            )
        else:
            project_id = st.text_input(
                "SonarQube Project Key",
                help="Project key from SonarQube (e.g., my-project:main)",
                placeholder="my-project:main"
            )
            
            project_url = st.text_input(
                "SonarQube Instance URL", 
                help="Base URL of your SonarQube instance",
                placeholder="https://sonarqube.example.com"
            )
    
    with col2:
        # Check if system has configured tokens for local setup
        system_tokens_available = True  # In local setup, system handles tokens
        
        if project_type == "gitlab":
            if system_tokens_available:
                st.info("🔐 **System-Managed Authentication**: Using configured GitLab system token")
                access_token = "system-managed"  # Placeholder - backend will use system token
            else:
                access_token = st.text_input(
                    "GitLab Personal Access Token",
                    type="password",
                    help="Token with 'api' scope to manage webhooks",
                    placeholder="glpat-xxxxxxxxxxxxxxxxxxxx"
                )
            
            webhook_events = st.multiselect(
                "Webhook Events to Monitor",
                ["pipeline", "merge_request"],
                default=["pipeline"],
                help="Select which events should trigger analysis"
            )
        else:
            if system_tokens_available:
                st.info("🔐 **System-Managed Authentication**: Using configured SonarQube system token")
                access_token = "system-managed"  # Placeholder - backend will use system token
            else:
                access_token = st.text_input(
                    "SonarQube User Token",
                    type="password", 
                    help="User token with webhook management permissions",
                    placeholder="squ_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                )
            
            webhook_events = ["quality_gate"]
            st.info("SonarQube subscriptions automatically monitor quality gate events")
    
    # Security information
    with st.expander("🔒 How It Works & Security", expanded=False):
        st.markdown("""
        **Self-Service Webhook Setup:**
        - Anyone can subscribe their projects for automatic analysis
        - System uses configured GitLab/SonarQube credentials for local setup
        - All webhook payloads are validated before processing
        - Each subscription gets unique security tokens
        
        **Authentication:**
        - **Local Setup**: System automatically handles API credentials
        - **Production**: Would require individual user tokens
        - All webhooks use secure authentication tokens
        
        **What happens when you subscribe:**
        1. ✅ System creates secure webhooks in your project using admin credentials
        2. 🔐 Webhook events are authenticated and validated  
        3. 🤖 Failed pipelines/quality gates trigger automatic AI analysis
        4. 💡 You receive actionable solutions via this UI
        5. 🚀 Optional: AI can create merge requests with fixes
        
        **Privacy & Ownership:**
        - You only see analysis for projects you've subscribed
        - Webhook tokens are unique per subscription
        - No cross-project data access
        """)
    
    # Create subscription
    if st.button("🚀 Create Subscription", type="primary", use_container_width=True):
        if project_id and project_url and access_token:
            with st.spinner("Creating subscription and configuring secure webhooks..."):
                try:
                    subscription_data = {
                        "project_type": project_type,
                        "project_id": project_id.strip(),
                        "project_url": project_url.rstrip('/'),
                        "access_token": access_token,
                        "webhook_events": webhook_events,
                        "metadata": {
                            "created_by": "streamlit_ui",
                            "created_at": datetime.utcnow().isoformat(),
                            "user_agent": "CI/CD Assistant UI",
                            "auth_mode": "system-managed" if access_token == "system-managed" else "user-provided"
                        }
                    }
                    
                    # Call webhook-handler subscription API
                    response = st.session_state.api_client.create_subscription(subscription_data)
                    
                    st.success("✅ Subscription created successfully!")
                    
                    # Show subscription details
                    col_info1, col_info2 = st.columns(2)
                    with col_info1:
                        st.info(f"**Subscription ID:** `{response['subscription_id']}`")
                        st.info(f"**Webhook URL:** `{response['webhook_url']}`")
                    with col_info2:
                        st.info(f"**Webhooks Created:** {len(response['webhook_ids'])}")
                        st.info(f"**Expires:** {response['expires_at'][:10]}")
                    
                    # Show next steps
                    st.markdown("### 🎉 Setup Complete!")
                    st.markdown("""
                    **What's been configured:**
                    - ✅ Secure webhooks with authentication
                    - ✅ Automatic failure detection
                    - ✅ Intelligent analysis pipeline
                    
                    **Next steps:**
                    1. � Monitor the 'Pipeline Failures' or 'Quality Issues' pages
                    2. 🚀 Trigger a test failure to see the system in action
                    3. 💬 Interact with the AI assistant for automated fixes
                    """)
                    
                    # Auto-refresh to show new subscription
                    st.balloons()
                    
                except Exception as e:
                    st.error(f"❌ Failed to create subscription: {e}")
                    if "authentication" in str(e).lower():
                        st.error("🔑 Please check your access token permissions")
                    elif "not found" in str(e).lower():
                        st.error("🔍 Please verify the project ID/key and URL")
        else:
            st.warning("⚠️ Please fill in all required fields")

with tab2:
    st.header("Manage Existing Subscriptions")
    
    # Fetch subscriptions
    def fetch_subscriptions():
        try:
            return asyncio.run(st.session_state.api_client.list_subscriptions())
        except Exception as e:
            log.error(f"Failed to fetch subscriptions: {e}")
            st.error(f"Failed to load projects: {e}")
            return []
    
    subscriptions = fetch_subscriptions()
    
    if subscriptions:
        st.success(f"Found {len(subscriptions)} subscription(s)")
        
        for sub in subscriptions:
            # Calculate expiry status
            expires_at = datetime.fromisoformat(sub['expires_at'].replace('Z', '+00:00'))
            days_left = (expires_at - datetime.utcnow()).days
            
            # Status indicators
            if sub['status'] == 'active':
                if days_left > 7:
                    status_color = "🟢"
                    status_text = "Active"
                elif days_left > 0:
                    status_color = "🟡"
                    status_text = f"Expires in {days_left} days"
                else:
                    status_color = "🔴"
                    status_text = "Expired"
            else:
                status_color = "🔴"
                status_text = "Inactive"
            
            with st.expander(f"{status_color} {sub['project_id']} ({sub['project_type'].title()})", expanded=days_left <= 7):
                col1, col2, col3 = st.columns([2, 1, 1])
                
                with col1:
                    st.markdown(f"**Project:** {sub['project_id']}")
                    st.markdown(f"**Type:** {sub['project_type'].title()}")
                    st.markdown(f"**Status:** {status_color} {status_text}")
                    st.markdown(f"**Webhooks:** {len(sub.get('webhook_ids', []))} configured")
                    st.markdown(f"**Created:** {sub.get('created_at', 'Unknown')[:10]}")
                    
                    if days_left <= 7 and days_left > 0:
                        st.warning(f"⚠️ Expires in {days_left} days - consider refreshing")
                    elif days_left <= 0:
                        st.error("🚨 Subscription has expired")
                
                with col2:
                    if st.button("🔄 Refresh", key=f"refresh_{sub['subscription_id']}", help="Extend expiry and verify webhooks"):
                        try:
                            with st.spinner("Refreshing subscription..."):
                                response = st.session_state.api_client.refresh_subscription(sub['subscription_id'])
                                if response.get('webhooks_active'):
                                    st.success("✅ Subscription refreshed!")
                                else:
                                    st.warning("⚠️ Subscription refreshed but some webhooks may be inactive")
                                st.rerun()
                        except Exception as e:
                            st.error(f"❌ Refresh failed: {e}")
                
                with col3:
                    if st.button("🗑️ Delete", key=f"delete_{sub['subscription_id']}", type="secondary", help="Remove subscription and all webhooks"):
                        try:
                            with st.spinner("Deleting subscription and removing webhooks..."):
                                st.session_state.api_client.delete_subscription(sub['subscription_id'])
                                st.success("✅ Subscription deleted!")
                                st.rerun()
                        except Exception as e:
                            st.error(f"❌ Delete failed: {e}")
                
                # Show webhook details
                if sub.get('webhook_ids'):
                    with st.expander("🔗 Webhook Details", expanded=False):
                        st.code(f"Webhook URL: {sub.get('webhook_url', 'N/A')}")
                        st.text(f"Webhook IDs: {', '.join(sub['webhook_ids'])}")
                        st.text(f"Events: {', '.join(sub.get('webhook_events', ['N/A']))}")
    else:
        st.info("📝 No subscriptions found. Create your first subscription in the 'New Subscription' tab!")
        
        # Quick setup button
        if st.button("➕ Create First Subscription", type="primary"):
            # Switch to first tab
            st.rerun()

with tab3:
    st.header("Webhook Status & System Health")
    
    # System metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Subscriptions", len(subscriptions))
    
    with col2:
        active_subs = len([s for s in subscriptions if s['status'] == 'active'])
        st.metric("Active Subscriptions", active_subs)
    
    with col3:
        gitlab_subs = len([s for s in subscriptions if s['project_type'] == 'gitlab'])
        st.metric("GitLab Projects", gitlab_subs)
    
    with col4:
        sonar_subs = len([s for s in subscriptions if s['project_type'] == 'sonarqube'])
        st.metric("SonarQube Projects", sonar_subs)
    
    # Health status
    st.subheader("🏥 Service Health")
    try:
        health = st.session_state.api_client.health_check()
        
        col_h1, col_h2 = st.columns(2)
        with col_h1:
            if health.get("strands_agent"):
                st.success("✅ Strands Agent: Operational")
            else:
                st.error("❌ Strands Agent: Unavailable")
        
        with col_h2:
            if health.get("webhook_handler"):
                st.success("✅ Webhook Handler: Operational")
            else:
                st.error("❌ Webhook Handler: Unavailable")
    except Exception as e:
        st.error(f"❌ Health check failed: {e}")
    
    # Subscription alerts
    st.subheader("⚠️ Alerts & Notifications")
    expiring_soon = []
    inactive_subs = []
    
    for sub in subscriptions:
        if sub['status'] != 'active':
            inactive_subs.append(sub)
        else:
            expires_at = datetime.fromisoformat(sub['expires_at'].replace('Z', '+00:00'))
            days_left = (expires_at - datetime.utcnow()).days
            if days_left <= 7:
                expiring_soon.append((sub, days_left))
    
    if expiring_soon:
        st.warning("🔔 **Subscriptions Expiring Soon:**")
        for sub, days_left in expiring_soon:
            if days_left <= 0:
                st.error(f"🚨 {sub['project_id']} has expired")
            else:
                st.warning(f"⚠️ {sub['project_id']} expires in {days_left} days")
    
    if inactive_subs:
        st.error("❌ **Inactive Subscriptions:**")
        for sub in inactive_subs:
            st.error(f"🔴 {sub['project_id']} is inactive")
    
    if not expiring_soon and not inactive_subs:
        st.success("✅ All subscriptions are healthy and up to date")
    
    # Quick actions
    st.subheader("⚡ Quick Actions")
    col_qa1, col_qa2, col_qa3 = st.columns(3)
    
    with col_qa1:
        if st.button("🔄 Refresh All", use_container_width=True):
            st.rerun()
    
    with col_qa2:
        if st.button("➕ Add New Project", use_container_width=True):
            st.switch_page("pages/project_setup.py")
    
    with col_qa3:
        if st.button("📊 View Sessions", use_container_width=True):
            st.switch_page("pages/pipeline_failures.py")

# Footer with helpful information
st.divider()
st.markdown("""
### 💡 How It Works

1. **Subscription Creation**: Creates secure webhooks in your GitLab/SonarQube projects
2. **Automatic Detection**: Monitors for pipeline failures and quality gate issues
3. **Intelligent Analysis**: AI analyzes failures and provides actionable solutions
4. **Automated Fixes**: Can create merge requests with fixes automatically
5. **Secure Communication**: All webhooks use authentication tokens and validation

**Need Help?** Check the Pipeline Failures or Quality Issues pages to see active analysis sessions.
""")
