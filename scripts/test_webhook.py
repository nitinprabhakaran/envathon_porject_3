#!/usr/bin/env python3
"""
Test script to simulate GitLab webhook for pipeline failure
"""
import requests
import json
from datetime import datetime

# Sample GitLab pipeline failure webhook payload
webhook_payload = {
    "object_kind": "pipeline",
    "object_attributes": {
        "id": 12345,
        "iid": 100,
        "name": "CI Pipeline",
        "ref": "main",
        "tag": False,
        "sha": "a1b2c3d4e5f6",
        "before_sha": "0000000000000000000000000000000000000000",
        "source": "push",
        "status": "failed",
        "detailed_status": "failed",
        "stages": ["build", "test", "deploy"],
        "created_at": datetime.utcnow().isoformat(),
        "finished_at": datetime.utcnow().isoformat(),
        "duration": 300,
        "queued_duration": 10,
        "url": "http://gitlab.example.com/project/-/pipelines/12345"
    },
    "user": {
        "id": 1,
        "name": "Test User",
        "username": "testuser",
        "email": "test@example.com"
    },
    "project": {
        "id": 123,
        "name": "test-project",
        "description": "Test project for CI/CD",
        "web_url": "http://gitlab.example.com/group/test-project",
        "path_with_namespace": "group/test-project",
        "default_branch": "main"
    },
    "commit": {
        "id": "a1b2c3d4e5f6",
        "message": "Fix: Update dependencies",
        "timestamp": datetime.utcnow().isoformat(),
        "url": "http://gitlab.example.com/group/test-project/-/commit/a1b2c3d4e5f6",
        "author": {
            "name": "Test User",
            "email": "test@example.com"
        }
    },
    "builds": [
        {
            "id": 380,
            "stage": "build",
            "name": "build-job",
            "status": "success",
            "created_at": datetime.utcnow().isoformat(),
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": datetime.utcnow().isoformat()
        },
        {
            "id": 381,
            "stage": "test",
            "name": "test-job",
            "status": "failed",
            "created_at": datetime.utcnow().isoformat(),
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": datetime.utcnow().isoformat(),
            "failure_reason": "script_failure"
        }
    ]
}

def test_webhook(url="http://localhost:8000/webhook/gitlab"):
    """Send test webhook to the agent"""
    print(f"🚀 Sending test webhook to {url}")
    
    headers = {
        "Content-Type": "application/json",
        "X-Gitlab-Event": "Pipeline Hook",
        "X-Gitlab-Token": "test-token"  # If configured
    }
    
    try:
        response = requests.post(url, json=webhook_payload, headers=headers)
        print(f"📡 Response Status: {response.status_code}")
        print(f"📄 Response Body: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            result = response.json()
            if "session_id" in result:
                print(f"\n✅ Success! Session ID: {result['session_id']}")
                print(f"🌐 View analysis at: http://localhost:8501/?session={result['session_id']}")
        else:
            print(f"\n❌ Error: {response.status_code}")
            
    except Exception as e:
        print(f"\n❌ Failed to send webhook: {e}")
        print("Make sure the agent is running on port 8000")

if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/webhook/gitlab"
    test_webhook(url)