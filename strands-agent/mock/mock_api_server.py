#!/usr/bin/env python3
"""
Enhanced mock API server with multiple test scenarios
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
import uuid
import json
import random

app = FastAPI(title="Mock CI/CD Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mock data with various scenarios
mock_sessions = {
    # 1. Active Java project failure
    "session-123": {
        "id": "session-123",
        "project_id": "6",
        "project_name": "java-project",
        "pipeline_id": "4",
        "branch": "main",
        "pipeline_source": "push",
        "job_name": "build-job",
        "commit_sha": "530886f05ec56e7555e963447ec742eff64e45b3",
        "commit_message": "feat: initial commit for Java application",
        "pipeline_url": "http://gitlab/envathon/java-project/-/pipelines/4",
        "status": "active",
        "created_at": "2025-01-26T10:00:00Z",
        "last_activity": "2025-01-26T10:30:00Z",
        "failed_stage": "build",
        "error_type": "dependency",
        "error_signature": "Missing JAR file: target/java-project-1.0.0.jar",
        "conversation_history": [
            {
                "role": "assistant",
                "content": "I've analyzed the pipeline failure. The Docker build failed because the JAR file was missing.",
                "timestamp": "2025-01-26T10:01:00Z",
                "cards": [
                    {
                        "type": "analysis",
                        "title": "Pipeline Failure Analysis",
                        "content": "The build stage failed during Docker image creation. The required JAR file 'target/java-project-1.0.0.jar' is missing.",
                        "confidence": 95,
                        "error_type": "build_artifact_missing"
                    },
                    {
                        "type": "solution",
                        "title": "Add Maven Build Step",
                        "confidence": 95,
                        "estimated_time": "5-10 minutes",
                        "content": "Add a Maven compile stage before Docker build to create the required JAR file.",
                        "fix_type": "config",
                        "code_changes": "stages:\n  - compile\n  - build\n\nmaven-build:\n  stage: compile\n  image: maven:3.8-openjdk-11\n  script:\n    - mvn clean package\n  artifacts:\n    paths:\n      - target/*.jar",
                        "actions": [
                            {"label": "Apply Fix", "action": "apply_fix"},
                            {"label": "View Details", "action": "view_details"}
                        ]
                    }
                ]
            }
        ],
        "applied_fixes": [],
        "successful_fixes": [],
        "webhook_data": {
            "project": {"id": "6", "name": "java-project"},
            "object_attributes": {"id": "4", "status": "failed"},
            "builds": [
                {"stage": "build", "status": "failed", "name": "build-job"}
            ]
        }
    },
    
    # 2. Python test failure
    "session-456": {
        "id": "session-456",
        "project_id": "7",
        "project_name": "python-project",
        "pipeline_id": "8",
        "branch": "feature/add-tests",
        "pipeline_source": "merge_request",
        "merge_request_id": "42",
        "job_name": "test-job",
        "commit_sha": "abc123def456",
        "commit_message": "fix: update test cases",
        "pipeline_url": "http://gitlab/envathon/python-project/-/pipelines/8",
        "status": "resolved",
        "created_at": "2025-01-26T09:00:00Z",
        "last_activity": "2025-01-26T09:45:00Z",
        "failed_stage": "test",
        "error_type": "test_failure",
        "error_signature": "pytest test_app.py::test_function failed",
        "conversation_history": [],
        "applied_fixes": [{"type": "code", "description": "Fixed failing test", "confidence": 90}],
        "successful_fixes": [{"type": "code", "description": "Fixed failing test", "applied_at": "2025-01-26T09:40:00Z"}],
        "webhook_data": {}
    },
    
    # 3. Long conversation history
    "session-789": {
        "id": "session-789",
        "project_id": "8",
        "project_name": "javascript-project",
        "pipeline_id": "15",
        "branch": "develop",
        "pipeline_source": "push",
        "job_name": "lint-job",
        "commit_sha": "789xyz123",
        "commit_message": "refactor: clean up code",
        "pipeline_url": "http://gitlab/envathon/javascript-project/-/pipelines/15",
        "status": "active",
        "created_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        "last_activity": datetime.now(timezone.utc).isoformat(),
        "failed_stage": "quality_scan",
        "error_type": "code_quality",
        "error_signature": "ESLint found 42 errors",
        "conversation_history": [
            {"role": "user", "content": "What's wrong with the pipeline?", "timestamp": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
            {"role": "assistant", "content": "The quality scan failed due to ESLint errors.", "timestamp": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
            {"role": "user", "content": "Can you show me the specific errors?", "timestamp": (datetime.now(timezone.utc) - timedelta(hours=1, minutes=50)).isoformat()},
            {"role": "assistant", "content": "Here are the main ESLint violations:", "cards": [{"type": "error", "title": "ESLint Errors", "content": "- Missing semicolons: 15 errors\n- Undefined variables: 10 errors\n- Unused variables: 17 errors"}], "timestamp": (datetime.now(timezone.utc) - timedelta(hours=1, minutes=45)).isoformat()},
            {"role": "user", "content": "How do I fix the semicolon issues?", "timestamp": (datetime.now(timezone.utc) - timedelta(hours=1, minutes=30)).isoformat()},
            {"role": "assistant", "content": "You can fix semicolon issues automatically.", "cards": [{"type": "solution", "title": "Auto-fix ESLint", "content": "Run: npm run lint -- --fix", "confidence": 100}], "timestamp": (datetime.now(timezone.utc) - timedelta(hours=1, minutes=25)).isoformat()},
        ],
        "applied_fixes": [],
        "successful_fixes": [],
        "webhook_data": {}
    },
    
    # 4. SonarQube quality gate failure
    "session-101": {
        "id": "session-101",
        "project_id": "9",
        "project_name": "microservice-api",
        "pipeline_id": "22",
        "branch": "main",
        "pipeline_source": "schedule",
        "job_name": "sonar-scan-job",
        "commit_sha": "def456abc789",
        "commit_message": "chore: nightly build",
        "pipeline_url": "http://gitlab/envathon/microservice-api/-/pipelines/22",
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_activity": datetime.now(timezone.utc).isoformat(),
        "failed_stage": "quality_scan",
        "error_type": "quality_gate",
        "error_signature": "SonarQube Quality Gate Failed: Coverage 45% < 80%",
        "conversation_history": [
            {
                "role": "assistant",
                "content": "Quality gate failure detected.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cards": [
                    {
                        "type": "error",
                        "title": "Quality Gate Failed",
                        "content": "Coverage: 45% (Required: 80%)\nCode Smells: 23\nVulnerabilities: 2\nBugs: 5"
                    },
                    {
                        "type": "history",
                        "title": "Similar Issues Found",
                        "issues": [
                            {"time_ago": "3 days ago", "description": "Coverage dropped to 50%", "fix": "Added unit tests", "fix_time": "2 hours", "successful": True},
                            {"time_ago": "1 week ago", "description": "Quality gate failed", "fix": "Refactored code", "fix_time": "4 hours", "successful": True}
                        ]
                    }
                ]
            }
        ],
        "applied_fixes": [],
        "successful_fixes": [],
        "webhook_data": {}
    },
    
    # 5. Empty conversation (new failure)
    "session-202": {
        "id": "session-202",
        "project_id": "10",
        "project_name": "frontend-app",
        "pipeline_id": "33",
        "branch": "hotfix/security-patch",
        "pipeline_source": "push",
        "job_name": "security-scan",
        "commit_sha": "aaa111bbb222",
        "commit_message": "fix: patch security vulnerability",
        "pipeline_url": "http://gitlab/envathon/frontend-app/-/pipelines/33",
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_activity": datetime.now(timezone.utc).isoformat(),
        "failed_stage": "security",
        "error_type": "security_vulnerability",
        "error_signature": "High severity vulnerability found in dependency",
        "conversation_history": [],
        "applied_fixes": [],
        "successful_fixes": [],
        "webhook_data": {}
    }
}

# Error injection for testing
ERROR_RATE = 0.1  # 10% chance of error

@app.get("/")
async def root():
    return {"name": "Mock CI/CD Agent API", "status": "operational"}

@app.get("/api/sessions/active")
async def get_active_sessions():
    """Return mock active sessions"""
    return [session for session in mock_sessions.values()]

@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Return specific session details"""
    if session_id in mock_sessions:
        return mock_sessions[session_id]
    
    # Generate a new mock session
    new_session = {
        "id": session_id,
        "project_id": str(random.randint(100, 999)),
        "project_name": f"project-{session_id[-3:]}",
        "pipeline_id": str(random.randint(1000, 9999)),
        "branch": random.choice(["main", "develop", "feature/test"]),
        "pipeline_source": random.choice(["push", "merge_request", "schedule"]),
        "job_name": random.choice(["build-job", "test-job", "deploy-job"]),
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_activity": datetime.now(timezone.utc).isoformat(),
        "failed_stage": random.choice(["build", "test", "deploy"]),
        "error_type": "unknown",
        "conversation_history": [],
        "applied_fixes": [],
        "successful_fixes": []
    }
    mock_sessions[session_id] = new_session
    return new_session

@app.post("/api/sessions/{session_id}/message")
async def send_message(session_id: str, request: Dict[str, Any]):
    """Mock message handling with error simulation"""
    
    # Simulate random errors
    if random.random() < ERROR_RATE:
        raise HTTPException(status_code=500, detail="Simulated server error for testing")
    
    message = request.get("message", "")
    
    if session_id not in mock_sessions:
        await get_session(session_id)
    
    session = mock_sessions[session_id]
    
    # Add user message
    session["conversation_history"].append({
        "role": "user",
        "content": message,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    # Generate contextual response
    if "fix" in message.lower():
        response_content = "I'll help you fix this issue. Based on the error analysis, here's what I recommend:"
        cards = [
            {
                "type": "solution",
                "title": "Recommended Fix",
                "confidence": 90,
                "estimated_time": "10-15 minutes",
                "content": f"For {session['error_type']} in {session['failed_stage']} stage:\n1. Check the {session['job_name']} configuration\n2. Update dependencies\n3. Retry the pipeline",
                "fix_type": "config",
                "code_changes": "# Example fix\nstages:\n  - build\n  - test\n  - deploy",
                "actions": [
                    {"label": "Apply Fix", "action": "apply_fix"},
                    {"label": "Create MR", "action": "create_mr"}
                ]
            }
        ]
    elif "explain" in message.lower():
        response_content = "Let me explain what happened in detail:"
        cards = [
            {
                "type": "analysis",
                "title": "Detailed Analysis",
                "content": f"The pipeline failed at the {session['failed_stage']} stage. Error type: {session['error_type']}. This occurred on branch '{session['branch']}' triggered by {session['pipeline_source']}.",
                "actions": []
            }
        ]
    elif "progress" in message.lower():
        response_content = "Here's the current progress on fixing this issue:"
        cards = [
            {
                "type": "progress",
                "title": "Fix Application Progress",
                "subtitle": "Applying recommended changes",
                "progress": 65,
                "steps": [
                    {"name": "Analyze error patterns", "status": "done"},
                    {"name": "Generate fix", "status": "done"},
                    {"name": "Apply changes", "status": "in_progress"},
                    {"name": "Validate fix", "status": "pending"},
                    {"name": "Create merge request", "status": "pending"}
                ]
            }
        ]
    else:
        response_content = f"I understand you're asking about: {message}. Let me analyze this for you."
        cards = [
            {
                "type": "default",
                "title": "Response",
                "content": f"Analyzing {session['error_type']} error in {session['project_name']}...",
                "actions": []
            }
        ]
    
    # Add assistant response
    session["conversation_history"].append({
        "role": "assistant",
        "content": response_content,
        "cards": cards,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    session["last_activity"] = datetime.now(timezone.utc).isoformat()
    
    return {
        "response": response_content,
        "cards": cards,
        "session_id": session_id
    }

@app.post("/api/sessions/{session_id}/apply-fix")
async def apply_fix(session_id: str, request: Dict[str, Any]):
    """Mock fix application"""
    if session_id in mock_sessions:
        fix_data = {
            "fix_id": request.get("fix_id", str(uuid.uuid4())),
            "type": "automated",
            "description": "Applied recommended fix",
            "applied_at": datetime.now(timezone.utc).isoformat()
        }
        mock_sessions[session_id]["applied_fixes"].append(fix_data)
        
        return {
            "status": "success",
            "fix_id": fix_data["fix_id"],
            "message": "Fix applied successfully"
        }
    
    raise HTTPException(status_code=404, detail="Session not found")

@app.post("/webhook/gitlab")
async def webhook_gitlab(request: Dict[str, Any]):
    """Mock webhook endpoint"""
    session_id = str(uuid.uuid4())
    project_id = request.get("project", {}).get("id", "99")
    pipeline_id = request.get("object_attributes", {}).get("id", "999")
    
    new_session = {
        "id": session_id,
        "project_id": str(project_id),
        "project_name": request.get("project", {}).get("name", f"project-{project_id}"),
        "pipeline_id": str(pipeline_id),
        "branch": request.get("object_attributes", {}).get("ref", "main"),
        "pipeline_source": request.get("object_attributes", {}).get("source", "push"),
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_activity": datetime.now(timezone.utc).isoformat(),
        "failed_stage": "build",
        "error_type": "build_failure",
        "error_signature": "Mock pipeline failure",
        "conversation_history": [
            {
                "role": "assistant",
                "content": "New pipeline failure detected. Analyzing...",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cards": [
                    {
                        "type": "analysis",
                        "title": "Pipeline Failure Detected",
                        "content": f"Pipeline {pipeline_id} in project {project_id} has failed.",
                        "confidence": 85
                    }
                ]
            }
        ],
        "applied_fixes": [],
        "successful_fixes": [],
        "webhook_data": request
    }
    
    mock_sessions[session_id] = new_session
    
    return {
        "status": "success",
        "session_id": session_id,
        "message": "Webhook processed"
    }

if __name__ == "__main__":
    import uvicorn
    print("Starting Enhanced Mock API Server on port 8000...")
    print("\nAvailable test sessions:")
    for sid, session in mock_sessions.items():
        print(f"  - {sid}: {session['project_name']}#{session['pipeline_id']} ({session['status']}) - {session['error_type']}")
    print("\nTest scenarios:")
    print("  1. Active Java build failure")
    print("  2. Resolved Python test failure (MR triggered)")
    print("  3. Long conversation with ESLint errors")
    print("  4. SonarQube quality gate failure")
    print("  5. Empty conversation - security scan")
    print("\n10% chance of random errors for testing error handling")
    uvicorn.run(app, host="0.0.0.0", port=8000)