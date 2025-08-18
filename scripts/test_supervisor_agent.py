#!/usr/bin/env python3
"""
Test script to verify SupervisorAgent implementation
"""

import asyncio
import sys
import os

# Add the strands-agent directory to the Python path
strands_agent_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'strands-agent')
sys.path.insert(0, strands_agent_path)

from agents.supervisor_agent import supervisor_agent

async def test_supervisor_agent():
    """Test the SupervisorAgent implementation"""
    
    # Mock webhook data for pipeline failure
    mock_webhook_data = {
        "object_attributes": {
            "id": "12345",
            "status": "failed",
            "stage": "test",
            "web_url": "https://gitlab.example.com/project/-/pipelines/12345"
        },
        "project": {
            "id": 67890,
            "name": "test-project",
            "namespace": {
                "name": "test-namespace"
            }
        }
    }
    
    mock_failure_context = {
        "event_type": "pipeline_failure",
        "pipeline_id": "12345",
        "project_id": "67890",
        "session_context": {
            "session_id": "test-session-123",
            "project_name": "test-project",
            "sonarqube_key": "test-namespace:test-project",
            "original_failure_type": "pipeline"
        }
    }
    
    print("🧪 Testing SupervisorAgent coordination...")
    
    try:
        # Test coordination
        result = await supervisor_agent.coordinate_failure_analysis(
            session_id="test-session-123",
            project_id="67890", 
            webhook_data=mock_webhook_data,
            failure_context=mock_failure_context
        )
        
        print("✅ SupervisorAgent coordination test completed")
        print(f"📊 Result length: {len(result)} characters")
        print(f"📝 Result preview: {result[:200]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ SupervisorAgent test failed: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_supervisor_agent())
    if not success:
        sys.exit(1)
    print("🎉 All tests passed!")
