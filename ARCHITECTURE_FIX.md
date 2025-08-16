# Session Deduplication Architecture Fix

## Problem Identified
The system was creating **2 separate sessions for a single SonarQube failure on a GitLab pipeline**:

1. **Pipeline Session**: Created by webhook-handler when GitLab pipeline fails
2. **Quality Session**: Created when strands-agent detects quality gate failure in logs

## Root Cause
- SonarQube webhooks were going through webhook-handler instead of directly to strands-agent
- This caused double session creation for the same failure

## Solution Implemented

### 1. Direct SonarQube Webhook Flow (Fixed)
```
SonarQube Quality Gate Fails
        ↓
strands-agent: /webhooks/sonarqube (DIRECT)
        ↓
Creates ONE quality session
        ↓
Analyzes quality issues directly
```

### 2. GitLab Pipeline with Quality Detection Flow (Working)
```
GitLab Pipeline Fails (with quality job)
        ↓
webhook-handler: /webhooks/gitlab  
        ↓
strands-agent detects quality failure in logs
        ↓
Updates session type from "pipeline" → "quality"
        ↓  
Runs quality analysis (not pipeline analysis)
```

### 3. Regular Pipeline Failure Flow (Unchanged)
```
GitLab Pipeline Fails (non-quality)
        ↓
webhook-handler: /webhooks/gitlab
        ↓
strands-agent: creates pipeline session
        ↓
Analyzes pipeline failure
```

## Key Changes Made

### webhook-handler/api/webhooks.py
- **REMOVED**: SonarQube session creation logic
- **REPLACED**: With redirect message to strands-agent
- SonarQube webhooks now return redirect instruction

### strands-agent/api/webhooks.py
- **ENHANCED**: Direct SonarQube webhook handling
- **ADDED**: Session deduplication for SonarQube webhooks
- **FIXED**: Method signatures to match working version
- **IMPROVED**: GitLab quality detection remains intact

### strands-agent/main.py
- **ADDED**: Webhooks router to enable direct handling
- **MADE**: Queue processor optional (disabled by default)

## Session Deduplication Logic

### For SonarQube (Direct Webhooks)
- Check for existing active quality session for the GitLab project
- If exists: Update with latest SonarQube data
- If not exists: Create new quality session

### For GitLab Pipeline (via webhook-handler)
- Check if pipeline failure contains quality gate failure
- If quality failure: Create quality session (or convert existing pipeline session)
- If regular failure: Create pipeline session
- Existing session check prevents duplicates

## Configuration Required

### SonarQube Webhooks
Configure SonarQube webhooks to point directly to:
```
http://strands-agent:8002/webhooks/sonarqube
```
**NOT** to webhook-handler

### GitLab Webhooks
Continue to point to webhook-handler:
```
http://webhook-handler:8001/webhooks/gitlab
```

## Testing the Fix

### Test Case 1: Direct SonarQube Quality Gate Failure
1. SonarQube quality gate fails
2. Should create **ONE** quality session
3. Should analyze quality issues directly

### Test Case 2: GitLab Pipeline with SonarQube Failure
1. GitLab pipeline fails on sonar-quality job
2. Should create **ONE** quality session (converted from pipeline)
3. Should analyze quality issues, not pipeline failure

### Test Case 3: Regular GitLab Pipeline Failure
1. GitLab pipeline fails on non-quality job
2. Should create **ONE** pipeline session
3. Should analyze pipeline failure normally

## Expected Results
- **No more duplicate sessions** for SonarQube failures
- **Faster quality analysis** (direct webhook, no queue processing)
- **Consistent session management** across all failure types
- **Preserved functionality** for regular pipeline failures

## Verification Steps
1. Restart strands-agent service
2. Configure SonarQube webhook URL to point to strands-agent
3. Trigger quality gate failure
4. Verify only ONE session created
5. Verify session type is "quality"
6. Verify analysis focuses on quality issues, not pipeline logs
