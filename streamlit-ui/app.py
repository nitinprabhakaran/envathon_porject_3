"""Streamlit main application"""
import streamlit as st
from utils.logger import setup_logger

# Setup logger
log = setup_logger()

# Page config
st.set_page_config(
    page_title="CI/CD Failure Assistant",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .stButton > button {
        width: 100%;
        background-color: #1f77b4;
        color: white;
    }
    .stButton > button:hover {
        background-color: #1a5490;
    }
    .success-box {
        padding: 1rem;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        border-radius: 0.25rem;
        color: #155724;
    }
    .error-box {
        padding: 1rem;
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        border-radius: 0.25rem;
        color: #721c24;
    }
    .analysis-box {
        padding: 1rem;
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<h1 class="main-header">🔧 CI/CD Failure Assistant</h1>', unsafe_allow_html=True)

# Navigation info
st.info("👈 Select **Pipeline Failures** or **Quality Issues** from the sidebar to begin")

# Sidebar
with st.sidebar:
    st.header("Navigation")
    st.page_link("pages/pipeline_failures.py", label="🚀 Pipeline Failures", icon="🚀")
    st.page_link("pages/quality_issues.py", label="📊 Quality Issues", icon="📊")
    
    st.divider()
    
    # System status
    st.header("System Status")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Status", "🟢 Online")
    with col2:
        st.metric("Sessions", "Loading...")

# Main content
st.header("Welcome to CI/CD Failure Assistant")

col1, col2 = st.columns(2)

with col1:
    st.subheader("🚀 Pipeline Failures")
    st.write("""
    Automatically analyze GitLab CI/CD pipeline failures:
    - Identify root causes
    - Get actionable solutions
    - Create merge requests with fixes
    - Track resolution progress
    """)
    
    if st.button("Go to Pipeline Failures", key="pipeline_btn"):
        st.switch_page("pages/pipeline_failures.py")

with col2:
    st.subheader("📊 Quality Issues")
    st.write("""
    Resolve SonarQube quality gate failures:
    - Analyze code quality issues
    - Fix bugs and vulnerabilities
    - Clean up code smells
    - Batch fix similar issues
    """)
    
    if st.button("Go to Quality Issues", key="quality_btn"):
        st.switch_page("pages/quality_issues.py")

st.divider()

# Features
st.header("Key Features")

feature_cols = st.columns(3)

with feature_cols[0]:
    st.markdown("""
    ### 🤖 AI-Powered Analysis
    - Intelligent root cause detection
    - Context-aware solutions
    - Confidence scoring
    """)

with feature_cols[1]:
    st.markdown("""
    ### 💬 Interactive Chat
    - Ask follow-up questions
    - Request clarifications
    - Explore alternatives
    """)

with feature_cols[2]:
    st.markdown("""
    ### 🔧 Automated Fixes
    - Generate merge requests
    - Apply batch fixes
    - Track success rates
    """)

# Footer
st.divider()
st.caption("CI/CD Failure Assistant v1.0.0 | Powered by Strands Agents")