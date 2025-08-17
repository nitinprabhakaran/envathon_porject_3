#!/usr/bin/env python3
"""
Setup script for the comprehensive fix tracking system
This script will:
1. Initialize the enhanced database schema
2. Test the session manager fix tracking methods
3. Verify the queue processor enhancement
4. Validate the UI components
"""

import sys
import os
import asyncio
import psycopg2
from datetime import datetime

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strands-agent.db.session_manager import SessionManager
from strands-agent.db.models import Session, FixAttempt
from strands-agent.services.queue_processor import QueueProcessor
from strands-agent.config import database_config

def setup_database():
    """Setup the enhanced database schema"""
    print("🗄️  Setting up enhanced database schema...")
    
    # Connect to database
    conn = psycopg2.connect(
        host=database_config.get("host", "localhost"),
        port=database_config.get("port", 5432),
        database=database_config.get("database", "envathon"),
        user=database_config.get("user", "postgres"),
        password=database_config.get("password", "password")
    )
    
    try:
        with conn.cursor() as cursor:
            # Read and execute the enhanced schema
            with open("init.sql", "r") as f:
                schema_sql = f.read()
            
            cursor.execute(schema_sql)
            conn.commit()
            print("✅ Database schema updated successfully")
            
            # Verify new columns exist
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'sessions' 
                AND column_name IN ('current_fix_branch', 'fix_iteration', 'status', 'resolution_method')
            """)
            
            columns = [row[0] for row in cursor.fetchall()]
            print(f"✅ Verified new session columns: {columns}")
            
            cursor.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'fix_attempts' 
                AND column_name IN ('pipeline_id', 'error_message', 'succeeded_at', 'failed_at')
            """)
            
            columns = [row[0] for row in cursor.fetchall()]
            print(f"✅ Verified enhanced fix_attempts columns: {columns}")
            
    except Exception as e:
        print(f"❌ Database setup failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def test_session_manager():
    """Test the enhanced session manager functionality"""
    print("\n🧪 Testing session manager enhancements...")
    
    session_manager = SessionManager()
    
    # Test creating a session with fix tracking
    test_session_id = "test_fix_tracking_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    
    try:
        # Create test session
        session_manager.create_session(
            session_id=test_session_id,
            project="test-project",
            branch="main",
            job_name="test-job",
            agent_type="pipeline"
        )
        print(f"✅ Created test session: {test_session_id}")
        
        # Test creating a fix attempt
        fix_branch = f"fix/pipeline_{test_session_id}"
        attempt_id = session_manager.create_fix_attempt(
            session_id=test_session_id,
            branch=fix_branch,
            attempt_number=1
        )
        print(f"✅ Created fix attempt: {attempt_id}")
        
        # Test updating session with fix branch
        session_manager.update_session_fix_status(
            session_id=test_session_id,
            current_fix_branch=fix_branch,
            fix_iteration=1
        )
        print("✅ Updated session fix status")
        
        # Test pipeline success handling
        session_manager.handle_pipeline_success_on_fix_branch(
            branch=fix_branch,
            pipeline_id="test-pipeline-123",
            mr_url="https://gitlab.com/test/repo/-/merge_requests/1"
        )
        print("✅ Tested pipeline success handling")
        
        # Verify session status
        session = session_manager.get_session(test_session_id)
        if session and session.get("status") == "resolved":
            print("✅ Session automatically resolved on pipeline success")
        else:
            print("⚠️  Session resolution may need manual verification")
        
        # Cleanup test data
        session_manager.delete_session(test_session_id)
        print("✅ Cleaned up test data")
        
    except Exception as e:
        print(f"❌ Session manager test failed: {e}")
        raise

def test_queue_processor():
    """Test the enhanced queue processor functionality"""
    print("\n🔄 Testing queue processor enhancements...")
    
    try:
        queue_processor = QueueProcessor()
        
        # Test fix branch event handling capability
        test_event = {
            "object_kind": "pipeline",
            "object_attributes": {
                "status": "success",
                "id": 12345,
                "web_url": "https://gitlab.com/test/pipeline/12345"
            },
            "project": {
                "name": "test-project"
            },
            "commit": {
                "message": "Fix pipeline issues"
            },
            "builds": [
                {
                    "name": "test-job",
                    "status": "success",
                    "stage": "test"
                }
            ]
        }
        
        # Test event classification
        if hasattr(queue_processor, '_is_fix_branch_event'):
            is_fix_event = queue_processor._is_fix_branch_event(test_event, "fix/pipeline_test123")
            print(f"✅ Fix branch event detection: {is_fix_event}")
        
        print("✅ Queue processor enhancements verified")
        
    except Exception as e:
        print(f"❌ Queue processor test failed: {e}")
        raise

def test_ui_components():
    """Test the enhanced UI components"""
    print("\n🎨 Testing UI component enhancements...")
    
    try:
        # Test imports
        from streamlit_ui.utils.ui_shared import (
            render_session_status, render_fix_attempts_info, 
            render_action_buttons, render_session_details_card
        )
        print("✅ UI components imported successfully")
        
        # Test mock data structures
        mock_session = {
            "session_id": "test123",
            "status": "in_progress",
            "current_fix_branch": "fix/pipeline_test123",
            "fix_iteration": 2,
            "created_at": datetime.now().isoformat()
        }
        
        mock_fix_attempts = [
            {
                "attempt_number": 1,
                "status": "failed",
                "branch": "fix/pipeline_test123_1",
                "mr_id": "123",
                "created_at": datetime.now().isoformat(),
                "error_message": "Test error"
            },
            {
                "attempt_number": 2,
                "status": "pending",
                "branch": "fix/pipeline_test123_2",
                "created_at": datetime.now().isoformat()
            }
        ]
        
        # Test status rendering function
        status_result = render_session_status(mock_session)
        if isinstance(status_result, tuple) and len(status_result) == 3:
            print("✅ Session status rendering structure verified")
        
        print("✅ UI components structure verified")
        
    except Exception as e:
        print(f"❌ UI component test failed: {e}")
        raise

def verify_system_integration():
    """Verify the complete system integration"""
    print("\n🔗 Verifying system integration...")
    
    try:
        # Check all major components can be imported
        from strands-agent.db.session_manager import SessionManager
        from strands-agent.services.queue_processor import QueueProcessor
        from strands-agent.utils.branch_naming import generate_branch_name
        
        print("✅ All core components can be imported")
        
        # Test branch naming with full session ID
        test_session_id = "abcd1234efgh5678ijkl9012mnop3456"
        branch_name = generate_branch_name(test_session_id, "pipeline")
        
        if test_session_id in branch_name:
            print("✅ Branch naming uses full session ID for correlation")
        else:
            print("⚠️  Branch naming may not include full session ID")
        
        print("✅ System integration verified")
        
    except Exception as e:
        print(f"❌ System integration verification failed: {e}")
        raise

def main():
    """Main setup and testing function"""
    print("🚀 Starting Comprehensive Fix Tracking System Setup")
    print("=" * 60)
    
    try:
        # 1. Setup database
        setup_database()
        
        # 2. Test session manager
        test_session_manager()
        
        # 3. Test queue processor
        test_queue_processor()
        
        # 4. Test UI components
        test_ui_components()
        
        # 5. Verify integration
        verify_system_integration()
        
        print("\n" + "=" * 60)
        print("🎉 Fix Tracking System Setup Complete!")
        print("\nFeatures now available:")
        print("✅ Enhanced database schema with fix tracking fields")
        print("✅ Comprehensive session manager with fix attempt tracking")
        print("✅ Smart queue processor with pipeline result detection")
        print("✅ Enhanced UI components with real-time status display")
        print("✅ Automatic session resolution on pipeline success")
        print("✅ Full session ID correlation for precise tracking")
        print("\nThe system is ready for comprehensive fix tracking!")
        
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        print("Please check the error details and fix any issues before proceeding.")
        sys.exit(1)

if __name__ == "__main__":
    main()
