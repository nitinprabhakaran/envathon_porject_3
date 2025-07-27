import streamlit as st
from typing import Dict, Any, Optional
import time
from loguru import logger

def render_card(card: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Render adaptive response cards"""
    card_type = card.get("type", "default")
    
    if card_type == "analysis":
        render_analysis_card(card)
    elif card_type == "solution":
        render_solution_card(card, session_data)
    elif card_type == "error":
        render_error_card(card)
    elif card_type == "progress":
        render_progress_card(card)
    elif card_type == "history":
        render_history_card(card)
    else:
        render_default_card(card)

def render_analysis_card(card: Dict[str, Any]):
    """Render analysis card"""
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>🔍 {card.get('title', 'Analysis')}</h4>
            <p>{card.get('content', '')}</p>
            <p><strong>Confidence:</strong> {card.get('confidence', 0)}%</p>
            <p><strong>Error Type:</strong> {card.get('error_type', 'Unknown').replace('_', ' ').title()}</p>
        </div>
        """, unsafe_allow_html=True)

def render_solution_card(card: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Render solution card with actions"""
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>💡 {card.get('title', 'Solution')}</h4>
            <p><strong>Confidence:</strong> {card.get('confidence', 0)}%</p>
            <p><strong>Estimated Time:</strong> {card.get('estimated_time', 'Unknown')}</p>
            <hr>
            <p>{card.get('content', '')}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Action buttons
        if actions := card.get('actions', []):
            cols = st.columns(len(actions))
            for i, action in enumerate(actions):
                with cols[i]:
                    button_key = f"action_{session_data.get('id', '')}_{int(time.time() * 1000)}_{i}"
                    if st.button(action['label'], key=button_key, use_container_width=True):
                        handle_action(action, session_data)

def render_error_card(card: Dict[str, Any]):
    """Render error card"""
    with st.container():
        st.error(f"""
        ### ❌ {card.get('title', 'Error')}
        {card.get('content', '')}
        """)

def render_progress_card(card: Dict[str, Any]):
    """Render progress card"""
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>⏳ {card.get('title', 'Progress')}</h4>
            <p>{card.get('subtitle', '')}</p>
        </div>
        """, unsafe_allow_html=True)
        
        if progress := card.get('progress'):
            st.progress(progress / 100)
        
        if steps := card.get('steps', []):
            for step in steps:
                if step.get('status') == 'done':
                    st.success(f"✓ {step.get('name', '')}")
                elif step.get('status') == 'in_progress':
                    st.info(f"⏳ {step.get('name', '')}")
                else:
                    st.text(f"○ {step.get('name', '')}")

def render_history_card(card: Dict[str, Any]):
    """Render history card"""
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>📜 {card.get('title', 'Similar Issues')}</h4>
        </div>
        """, unsafe_allow_html=True)
        
        if issues := card.get('issues', []):
            for issue in issues:
                with st.expander(f"{issue.get('time_ago', '')} - {issue.get('description', '')}"):
                    st.write(f"**Fix:** {issue.get('fix', 'N/A')}")
                    st.write(f"**Time to fix:** {issue.get('fix_time', 'N/A')}")
                    if issue.get('successful'):
                        st.success("✓ Successfully resolved")

def render_default_card(card: Dict[str, Any]):
    """Render default card"""
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>{card.get('title', 'Information')}</h4>
            <p>{card.get('content', '')}</p>
        </div>
        """, unsafe_allow_html=True)

def handle_action(action: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Handle card actions"""
    import asyncio
    from utils.api_client import APIClient
    
    action_type = action.get('action')
    
    if action_type == "apply_fix":
        with st.spinner("Applying fix..."):
            message = "Apply the fix you suggested"
    elif action_type == "create_mr":
        with st.spinner("Creating merge request..."):
            message = "Create a merge request with the fixes you suggested"
    elif action_type == "view_details":
        message = "Show me more details about this error"
    elif action_type == "retry_analysis":
        message = "Retry the analysis"
    else:
        message = f"Execute action: {action_type}"
    
    # Send message to agent
    if session_data and session_data.get('id'):
        client = APIClient()
        result = asyncio.run(client.send_message(
            session_data['id'],
            message
        ))
        st.rerun()