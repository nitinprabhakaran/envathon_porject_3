import streamlit as st
from typing import Dict, Any, Optional
import time
from loguru import logger

def render_card(card: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Render different types of UI cards with session context"""
    card_type = card.get("type", "default")
    
    if card_type == "analysis":
        render_analysis_card(card, session_data)
    elif card_type == "solution":
        render_solution_card(card, session_data)
    elif card_type == "error":
        render_error_card(card, session_data)
    elif card_type == "progress":
        render_progress_card(card, session_data)
    elif card_type == "history":
        render_history_card(card, session_data)
    elif card_type == "recommendation":
        render_recommendation_card(card, session_data)
    else:
        render_default_card(card, session_data)

def render_analysis_card(card: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Render pipeline failure analysis card"""
    # Get data from card or fall back to session data
    if session_data:
        project = card.get('project', session_data.get('project_name', 'N/A'))
        pipeline_id = card.get('pipeline_id', session_data.get('pipeline_id', 'N/A'))
        failed_stage = card.get('failed_stage', session_data.get('failed_stage', 'N/A'))
    else:
        project = card.get('project', 'N/A')
        pipeline_id = card.get('pipeline_id', 'N/A')
        failed_stage = card.get('failed_stage', 'N/A')
    
    # Get confidence from card root level first, then try other locations
    confidence = card.get('confidence', 0)
    
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>🔴 {card.get('title', 'Pipeline Failure Analysis')}</h4>
            <p><strong>Project:</strong> {project}</p>
            <p><strong>Pipeline:</strong> {pipeline_id}</p>
            <p><strong>Failed Stage:</strong> {failed_stage}</p>
            <hr>
            <p><strong>🎯 Root Cause:</strong> {card.get('root_cause', card.get('content', 'Analyzing...'))}</p>
            <p><strong>📊 Confidence:</strong> {confidence}%</p>
            <p><strong>⏱️ Estimated Fix Time:</strong> {card.get('estimated_time', 'Unknown')}</p>
            <p><strong>🔍 Error Type:</strong> {card.get('error_type', 'Unknown')}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Action buttons
        if actions := card.get('actions', []):
            cols = st.columns(len(actions))
            for i, action in enumerate(actions):
                with cols[i]:
                    if st.button(action['label'], key=f"action_{card.get('id', int(time.time() * 1000))}_{i}"):
                        handle_action(action, session_data)

def render_solution_card(card: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Render solution suggestion card"""
    with st.container():
        confidence = card.get('confidence', 0)
        confidence_color = "#28a745" if confidence >= 80 else "#ffc107" if confidence >= 60 else "#dc3545"
        
        st.markdown(f"""
        <div class="card-container">
            <h4>💡 {card.get('title', 'Recommended Solution')}</h4>
            <p><strong>Type:</strong> {card.get('fix_type', 'General')}</p>
            <p><strong>Confidence:</strong> <span style="color: {confidence_color}">{confidence}%</span></p>
            <p><strong>Estimated Time:</strong> {card.get('estimated_time', 'Unknown')}</p>
            <hr>
            <p>{card.get('content', '')}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Show code changes if present
        if code_changes := card.get('code_changes'):
            with st.expander("View Fix steps"):
                st.code(code_changes, language=card.get('language', 'yaml'))
        
        # Action buttons
        if actions := card.get('actions', []):
            cols = st.columns(len(actions))
            for i, action in enumerate(actions):
                # Skip "Apply Fix" button
                if action.get('action') == 'apply_fix':
                    continue

                with cols[i]:
                    # Generate unique key using card content hash
                    import hashlib
                    card_hash = hashlib.md5(
                        f"{card.get('title', '')}{card.get('content', '')}{i}".encode()
                    ).hexdigest()[:8]
                    button_key = f"solution_{card_hash}_{i}"
                    
                    if st.button(action['label'], key=button_key):
                        handle_action(action, session_data)

def render_error_card(card: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Render error card"""
    st.error(f"**{card.get('title', 'Error')}**\n\n{card.get('content', '')}")

def render_progress_card(card: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Render progress card"""
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>🔧 {card.get('title', 'Fix Application Progress')}</h4>
            <p>{card.get('subtitle', '')}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Progress bar
        progress = card.get('progress', 0)
        st.progress(progress / 100)
        st.caption(f"{progress}% Complete")
        
        # Steps
        if steps := card.get('steps', []):
            for step in steps:
                status_icon = "✅" if step['status'] == 'done' else "🔄" if step['status'] == 'in_progress' else "⏳"
                st.markdown(f"{status_icon} {step['name']}")

def render_history_card(card: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Render historical context card"""
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>📊 {card.get('title', 'Similar Issues Found')}</h4>
            <p>{card.get('subtitle', '')}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Historical issues
        if issues := card.get('issues', []):
            for issue in issues:
                with st.expander(f"🕐 {issue.get('time_ago', '')} - {issue.get('description', '')}"):
                    st.write(f"**Fix Applied:** {issue.get('fix', 'N/A')}")
                    st.write(f"**Time to Fix:** {issue.get('fix_time', 'N/A')}")
                    st.write(f"**Success:** {'✅ Yes' if issue.get('successful') else '❌ No'}")

def render_recommendation_card(card: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Render recommendation card"""
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>💡 {card.get('title', 'Recommendations')}</h4>
            <p>{card.get('content', '')}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # List of recommendations
        if items := card.get('items', []):
            for item in items:
                st.markdown(f"• {item}")
        
        # Action buttons
        if actions := card.get('actions', []):
            cols = st.columns(len(actions))
            for i, action in enumerate(actions):
                with cols[i]:
                    if st.button(action['label'], key=f"rec_{int(time.time() * 1000)}_{i}"):
                        handle_action(action, session_data)

def render_default_card(card: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Render default card"""
    with st.container():
        st.markdown(f"""
        <div class="card-container">
            <h4>{card.get('title', 'Information')}</h4>
            <p>{card.get('content', '')}</p>
        </div>
        """, unsafe_allow_html=True)

def handle_action(action: Dict[str, Any], session_data: Optional[Dict[str, Any]] = None):
    """Handle card action button clicks"""
    import asyncio
    from utils.api_client import APIClient
    
    action_type = action.get('action')
    action_data = action.get('data', {})
    
    if action_type == "apply_fix":
        st.session_state.applying_fix = True
        with st.spinner("Applying fix..."):
            client = APIClient()
            fix_id = action_data.get('fix_id', f"fix-{int(time.time())}")
            logger.info(f"Sending apply_fix request: {fix_id}")
            result = asyncio.run(client.apply_fix(
                session_data['id'], 
                fix_id, 
                action_data
            ))
            logger.info(f"Apply fix response: {result.get('status')}")
            if result.get('status') == 'success':
                st.success("✅ Fix applied successfully!")
                st.rerun()
            else:
                st.error(f"Failed to apply fix: {result.get('error')}")
                
    elif action_type == "create_mr":
        st.session_state.creating_mr = True
        with st.spinner("Creating merge request..."):
            client = APIClient()
            fix_id = action_data.get('fix_id', f"mr-{int(time.time())}")
            logger.info(f"Sending create_mr request: {fix_id}")
            result = asyncio.run(client.create_merge_request(
                session_data['id'],
                {'fix_id': fix_id, 'fix_data': action_data}
            ))
            logger.info(f"Create MR response: {result.get('status')}")
            if result.get('status') == 'success':
                mr_info = result.get('merge_request', {})
                st.success(f"✅ Merge request created!")
                st.markdown(f"**MR #{mr_info.get('iid')}**: [{mr_info.get('title')}]({mr_info.get('url')})")
                st.balloons()
            else:
                st.error(f"Failed to create MR: {result.get('error')}")
                
    elif action_type == "view_details":
        st.session_state.show_details = True
        with st.expander("📋 Fix Details", expanded=True):
            st.json(action_data)
            
    elif action_type == "view_docs":
        if url := action.get('url'):
            st.markdown(f"[Open Documentation]({url})")
            
    else:
        st.info(f"Action: {action_type}")