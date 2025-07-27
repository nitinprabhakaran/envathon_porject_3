import streamlit as st
from typing import Dict, Any, List
import time

def render_quality_card(card: Dict[str, Any], session_data: Dict[str, Any]):
    """Render quality-specific cards"""
    card_type = card.get("type", "default")
    
    if card_type == "quality_summary":
        render_quality_summary_card(card, session_data)
    elif card_type == "issue_category":
        render_issue_category_card(card, session_data)
    elif card_type == "batch_fix":
        render_batch_fix_card(card, session_data)
    else:
        render_default_quality_card(card, session_data)

def render_quality_summary_card(card: Dict[str, Any], session_data: Dict[str, Any]):
    """Render quality gate summary card"""
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>🚨 {card.get('title', 'Quality Gate Failed')}</h4>
            <hr>
            <div style="display: flex; justify-content: space-around;">
                <div style="text-align: center;">
                    <h2 style="color: #dc3545;">{card.get('bugs', 0)}</h2>
                    <p>🐛 Bugs</p>
                </div>
                <div style="text-align: center;">
                    <h2 style="color: #ff6b6b;">{card.get('vulnerabilities', 0)}</h2>
                    <p>🔒 Vulnerabilities</p>
                </div>
                <div style="text-align: center;">
                    <h2 style="color: #ffc107;">{card.get('code_smells', 0)}</h2>
                    <p>💩 Code Smells</p>
                </div>
            </div>
            <hr>
            <p><strong>Total Effort:</strong> {card.get('effort', 'Unknown')}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Action buttons
        if actions := card.get('actions', []):
            cols = st.columns(len(actions))
            for i, action in enumerate(actions):
                with cols[i]:
                    button_key = f"quality_{int(time.time() * 1000)}_{i}"
                    if st.button(action['label'], key=button_key):
                        handle_quality_action(action, session_data)

def render_issue_category_card(card: Dict[str, Any], session_data: Dict[str, Any]):
    """Render issue category card"""
    issue_type = card.get('issue_type', 'Issues')
    icon = card.get('icon', '📋')
    
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>{icon} {card.get('title', issue_type)}</h4>
            <p><strong>Count:</strong> {card.get('count', 0)} issues</p>
            <p><strong>Severity Breakdown:</strong></p>
            <ul>
                <li>🔴 Critical: {card.get('critical', 0)}</li>
                <li>🟡 Major: {card.get('major', 0)}</li>
                <li>🟢 Minor: {card.get('minor', 0)}</li>
            </ul>
            <p><strong>Estimated Effort:</strong> {card.get('effort', 'Unknown')}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Show sample issues
        if issues := card.get('sample_issues', []):
            with st.expander("View Sample Issues"):
                for issue in issues[:5]:
                    st.markdown(f"- {issue.get('message', 'No message')}")

def render_batch_fix_card(card: Dict[str, Any], session_data: Dict[str, Any]):
    """Render batch fix proposal card"""
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>🛠️ {card.get('title', 'Batch Fix Proposal')}</h4>
            <p>{card.get('description', '')}</p>
            <hr>
            <p><strong>Issues to Fix:</strong> {card.get('issue_count', 0)}</p>
            <p><strong>Files Affected:</strong> {card.get('files_affected', 0)}</p>
            <p><strong>Total Effort:</strong> {card.get('effort', 'Unknown')}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Fix details
        if fixes := card.get('fixes', []):
            with st.expander("View Fix Details"):
                for fix in fixes:
                    st.markdown(f"✓ {fix}")
        
        # Actions
        if actions := card.get('actions', []):
            cols = st.columns(len(actions))
            for i, action in enumerate(actions):
                with cols[i]:
                    button_key = f"batch_{int(time.time() * 1000)}_{i}"
                    if st.button(action['label'], key=button_key):
                        handle_quality_action(action, session_data)

def render_default_quality_card(card: Dict[str, Any], session_data: Dict[str, Any]):
    """Render default quality card"""
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>{card.get('title', 'Quality Information')}</h4>
            <p>{card.get('content', '')}</p>
        </div>
        """, unsafe_allow_html=True)

def handle_quality_action(action: Dict[str, Any], session_data: Dict[str, Any]):
    """Handle quality card actions"""
    import asyncio
    from utils.api_client import APIClient
    
    action_type = action.get('action')
    
    if action_type == "fix_security":
        st.info("Preparing security fixes...")
        # TODO: Implement security fix batch
        
    elif action_type == "create_batch_mr":
        with st.spinner("Creating batch merge request..."):
            client = APIClient()
            result = asyncio.run(client.create_merge_request(
                session_data['id'],
                {'fix_type': 'batch_quality', 'action_data': action.get('data', {})}
            ))
            if result.get('status') == 'success':
                st.success("Batch MR created successfully!")
            else:
                st.error(f"Failed to create MR: {result.get('error')}")
                
    elif action_type == "view_in_sonarqube":
        if url := action.get('url'):
            st.markdown(f"[Open in SonarQube]({url})")
    
    else:
        st.info(f"Action: {action_type}")