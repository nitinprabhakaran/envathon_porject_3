# CI/CD Pipeline Failure Analysis System - Technical Design Document

## 1. System Overview

### 1.1 Purpose
An intelligent CI/CD pipeline failure analysis system that automatically diagnoses GitLab pipeline failures AND SonarQube quality gate failures, provides actionable fixes, and maintains conversational context for iterative debugging sessions lasting up to 4 hours.

### 1.2 Key Components
- **GitLab Webhook Integration**: Receives pipeline failure notifications
- **SonarQube Webhook Integration**: Receives quality gate failure notifications
- **AWS Strands Agent**: Single intelligent agent with specialized tools
- **Session Management**: Persistent conversation state with PostgreSQL
- **Vector Knowledge Base**: Historical error patterns and solutions using Qdrant
- **MCP Integration**: GitLab and SonarQube tools integrated into agent container
  - GitLab MCP Server: https://github.com/nguyenvanduocit/gitlab-mcp
  - SonarQube MCP Server: https://github.com/sonarsource/sonarqube-mcp-server
- **Streamlit UI**: Interactive dashboard with adaptive response cards and multi-tab interface

### 1.3 Technology Stack
- **Agent Framework**: AWS Strands Agents SDK
  - GitHub: https://github.com/strands-agents/sdk-python
  - Documentation: https://strandsagents.com/
- **LLM**: Claude 3.5 Sonnet via Bedrock/Anthropic
- **MCP Servers**: GitLab MCP + SonarQube MCP (integrated)
  - GitLab MCP: https://github.com/nguyenvanduocit/gitlab-mcp
  - SonarQube MCP: https://github.com/sonarsource/sonarqube-mcp-server
- **Database**: PostgreSQL (sessions) + Qdrant (vectors)
- **UI**: Streamlit with adaptive cards and tabbed interface
- **Deployment**: Docker Compose

## 2. System Architecture

### 2.1 High-Level Architecture Diagram

```
                GitLab Pipeline Failure          SonarQube Quality Gate Failure
                        │                                    │
                        ▼                                    ▼
               ┌─────────────────────┐              ┌─────────────────────┐
               │   Webhook Receiver  │              │   Webhook Receiver  │
               │ /webhook/gitlab     │              │ /webhook/sonarqube  │
               └─────────┬───────────┘              └─────────┬───────────┘
                        │                                    │
                        ▼                                    ▼
               ┌─────────────────────────────────────────────────────────┐
               │                    Session Manager                       │
               │  - Create/Get ID (session_type: pipeline/quality)       │
               │  - Context Loading                                      │
               └─────────┬───────────────────────────────────┬───────────┘
                        │                                    │
          ┌─────────────┴─────────────┐                     │
          ▼                           ▼                     │
┌─────────────────┐         ┌─────────────────┐            │
│   PostgreSQL    │         │     Qdrant      │            │
│   (Sessions)    │         │  (Vector DB)    │            │
└─────────────────┘         └─────────────────┘            │
                        │                                    │
                        ▼                                    ▼
               ┌─────────────────────────────────────────────────────────┐
               │                   Strands Agent Container                │
               │  ┌─────────────────────────────────────────────────┐   │
               │  │ Agent Core (Pipeline & Quality Analysis)        │   │
               │  ├─────────────────────────────────────────────────┤   │
               │  │ GitLab MCP Tools                                │   │
               │  ├─────────────────────────────────────────────────┤   │
               │  │ SonarQube MCP Tools (Enhanced)                  │   │
               │  ├─────────────────────────────────────────────────┤   │
               │  │ Custom Analysis Tools                           │   │
               │  └─────────────────────────────────────────────────┘   │
               └─────────┬───────────────────────────────────────────────┘
                        │
                        ▼
               ┌─────────────────────────────────────────────────────────┐
               │                    Streamlit UI                         │
               │  ┌─────────────────────────────────────────────────┐   │
               │  │ Tab 1: Pipeline Failures │ Tab 2: Quality Issues │   │
               │  ├─────────────────────────────────────────────────┤   │
               │  │ - Adaptive Cards         │ - Quality Dashboard  │   │
               │  │ - Session Context        │ - Issue Categories  │   │
               │  │ - Action Buttons         │ - Batch Fix Options │   │
               │  └─────────────────────────────────────────────────┘   │
               └─────────────────────────────────────────────────────────┘
```

### 2.2 Container Architecture

```
Docker Compose Services:
┌─────────────────────────────────────────────────────┐
│                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │   GitLab    │  │  SonarQube  │  │ PostgreSQL  │  │
│  │ (External)  │  │ (External)  │  │             │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
│                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │   Qdrant    │  │   Strands   │  │ Streamlit   │  │
│  │ Vector DB   │  │   Agent     │  │     UI      │  │
│  │             │  │ + MCP Tools │  │  (Tabbed)   │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

## 3. Data Flow Architecture

### 3.1 Pipeline Failure Flow (Existing)
[Previous pipeline failure flow remains the same]

### 3.2 SonarQube Quality Gate Failure Flow (New)

```
SonarQube Quality Gate Fails
        │
        ▼
Webhook → POST /webhook/sonarqube
        │
        ▼
┌───────────────────────┐
│ Webhook Processor     │
│ 1. Parse quality data │
│ 2. Extract project key│
│ 3. Create session ID  │
└───────┬───────────────┘
        │
        ▼
┌───────────────────────┐
│ Session Manager       │
│ 1. Store in DB        │
│ 2. Set type="quality" │
│ 3. Set 4hr expiry     │
└───────┬───────────────┘
        │
        ▼
┌───────────────────────┐
│ Quality Analysis      │
│ 1. Get gate details   │
│ 2. Fetch all issues   │
│ 3. Categorize by type │
└───────┬───────────────┘
        │
        ▼
┌───────────────────────┐
│ Strands Agent         │
│ 1. SonarQube MCP tools│
│ 2. Code analysis      │
│ 3. Fix generation     │
│ 4. Batch solutions    │
└───────┬───────────────┘
        │
        ▼
┌───────────────────────┐
│ Response Formatter    │
│ 1. Quality dashboard  │
│ 2. Issue cards        │
│ 3. Batch MR option    │
└───────┬───────────────┘
        │
        ▼
Quality Analysis Dashboard
```

## 4. Database Design

### 4.1 PostgreSQL Schema (Updated)

```sql
-- Sessions table (updated with session_type)
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id VARCHAR(255) NOT NULL,
    pipeline_id VARCHAR(255),  -- Nullable for quality sessions
    session_type VARCHAR(20) DEFAULT 'pipeline', -- 'pipeline' or 'quality'
    commit_hash VARCHAR(40),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '4 hours'),
    status VARCHAR(50) DEFAULT 'active', -- active, resolved, abandoned
    
    -- Failure context (for pipeline type)
    failed_stage VARCHAR(100),
    error_type VARCHAR(100), -- build, test, deploy, lint, quality_gate
    error_signature TEXT,
    logs_summary TEXT,
    
    -- Quality context (for quality type)
    quality_gate_status VARCHAR(20), -- ERROR, WARN, OK
    total_issues INTEGER DEFAULT 0,
    critical_issues INTEGER DEFAULT 0,
    major_issues INTEGER DEFAULT 0,
    
    -- Conversation data
    conversation_history JSONB DEFAULT '[]',
    applied_fixes JSONB DEFAULT '[]',
    successful_fixes JSONB DEFAULT '[]',
    
    -- Metadata
    tokens_used INTEGER DEFAULT 0,
    tools_called JSONB DEFAULT '[]',
    user_feedback JSONB DEFAULT '{}',
    webhook_data JSONB DEFAULT '{}',
    
    -- Additional fields
    branch VARCHAR(255),
    pipeline_source VARCHAR(50),
    job_name VARCHAR(255),
    project_name VARCHAR(255),
    merge_request_id VARCHAR(50),
    commit_sha VARCHAR(40),
    pipeline_url TEXT
);

-- Quality issues table (new)
CREATE TABLE quality_issues (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    issue_key VARCHAR(255) UNIQUE,
    issue_type VARCHAR(50), -- BUG, VULNERABILITY, CODE_SMELL
    severity VARCHAR(20), -- BLOCKER, CRITICAL, MAJOR, MINOR, INFO
    component VARCHAR(255),
    file_path TEXT,
    line_number INTEGER,
    message TEXT,
    rule_key VARCHAR(255),
    effort VARCHAR(50),
    suggested_fix TEXT,
    fix_confidence FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Quality fixes table (new)
CREATE TABLE quality_fixes (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    issue_ids TEXT[], -- Array of issue IDs being fixed
    fix_type VARCHAR(50), -- batch, individual
    mr_url TEXT,
    status VARCHAR(20), -- proposed, applied, merged
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Historical fixes table (existing - no changes)
CREATE TABLE historical_fixes (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    error_signature_hash VARCHAR(64),
    fix_description TEXT,
    fix_type VARCHAR(50),
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success_confirmed BOOLEAN,
    confidence_score FLOAT,
    project_context JSONB
);

-- Learning feedback table (existing - no changes)
CREATE TABLE agent_feedback (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    interaction_type VARCHAR(50),
    interaction_data JSONB,
    outcome VARCHAR(20),
    feedback_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_sessions_project_id ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_pipeline_id ON sessions(pipeline_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(session_type);
CREATE INDEX IF NOT EXISTS idx_quality_issues_session ON quality_issues(session_id);
CREATE INDEX IF NOT EXISTS idx_quality_issues_type ON quality_issues(issue_type);
CREATE INDEX IF NOT EXISTS idx_quality_issues_severity ON quality_issues(severity);
```

### 4.2 Vector Database Collections (Enhanced)

**New Collections for Quality Analysis:**
```yaml
quality_patterns:
  description: "Common quality issue patterns and their fixes"
  vector_size: 1536
  payload_schema:
    issue_type: string
    severity: string
    rule_key: string
    fix_pattern: string
    success_rate: float
    language: string

code_smell_fixes:
  description: "Successful code smell remediation patterns"
  vector_size: 1536
  payload_schema:
    smell_type: string
    before_code: string
    after_code: string
    effort_saved: string
    projects_fixed: integer
```

## 5. Strands Agent Architecture (Enhanced)

### 5.1 Enhanced Tool Structure

```
Strands Agent Container:
├── Agent Core (Claude 3.5 Sonnet)
├── Pipeline Analysis Tools (Existing):
│   ├── @tool analyze_pipeline_logs()
│   ├── @tool extract_error_signature()
│   └── ... (other pipeline tools)
├── Quality Analysis Tools (New):
│   ├── @tool analyze_quality_gate()
│   ├── @tool get_quality_issues_by_type()
│   ├── @tool suggest_quality_fixes()
│   ├── @tool create_batch_quality_mr()
│   └── @tool prioritize_quality_issues()
├── GitLab MCP Tools (Existing)
└── SonarQube MCP Tools (Enhanced):
    ├── get_quality_gate_details()
    ├── get_all_project_issues()
    ├── get_issue_code_context()
    ├── get_quality_metrics_trend()
    └── get_rule_descriptions()
```

### 5.2 Quality Analysis Agent Flow

```
Quality Gate Failure Received
        │
        ▼
1. Initial Quality Assessment
   ├── get_quality_gate_details()
   ├── get_all_project_issues()
   └── categorize_by_severity()
        │
        ▼
2. Issue Analysis & Grouping
   ├── Group similar issues
   ├── Identify patterns
   └── Check fix history
        │
        ▼
3. Fix Generation
   ├── Generate fixes per category
   ├── Estimate effort
   └── Create batch strategy
        │
        ▼
4. Response Generation
   ├── Quality dashboard data
   ├── Issue cards by type
   └── Batch MR option
```

## 6. SonarQube Integration Design

### 6.1 Webhook Configuration

**SonarQube Webhook Endpoint**: `/webhook/sonarqube`

**Webhook Payload Structure:**
```json
{
  "serverUrl": "http://sonarqube:9000",
  "taskId": "AXoMyIMinyYEjuxvXXXX",
  "status": "SUCCESS",
  "analysedAt": "2025-01-27T10:00:00+0000",
  "revision": "c6e4c6f4e5f6a7b8c9d0",
  "changedAt": "2025-01-27T09:55:00+0000",
  "project": {
    "key": "envathon_java-project",
    "name": "java-project",
    "url": "http://sonarqube:9000/dashboard?id=envathon_java-project"
  },
  "branch": {
    "name": "main",
    "type": "BRANCH",
    "isMain": true
  },
  "qualityGate": {
    "name": "envathon-gate",
    "status": "ERROR",
    "conditions": [
      {
        "metric": "new_reliability_rating",
        "operator": "GREATER_THAN",
        "value": "1",
        "status": "ERROR",
        "errorThreshold": "1"
      },
      {
        "metric": "new_vulnerabilities",
        "operator": "GREATER_THAN",
        "value": "3",
        "status": "ERROR",
        "errorThreshold": "0"
      }
    ]
  },
  "properties": {}
}
```

### 6.2 Quality Analysis Features

**Issue Categorization:**
- **Security**: Vulnerabilities, security hotspots
- **Reliability**: Bugs, potential crashes
- **Maintainability**: Code smells, technical debt

**Fix Strategies:**
- **Batch Fixes**: Group similar issues (e.g., all unused imports)
- **Priority Fixes**: Security vulnerabilities first
- **Quick Wins**: Low-effort, high-impact fixes

**MR Generation:**
- One MR with multiple commits (one per issue category)
- Clear commit messages referencing SonarQube rules
- Automated testing considerations

## 7. Streamlit UI Design (Enhanced)

### 7.1 UI Architecture - Tabbed Interface

```
Streamlit Application (Enhanced):
├── Header (Global Navigation)
│   ├── System status
│   └── Tab selector
├── Tab 1: Pipeline Failures (Existing)
│   ├── Left: Pipeline list
│   ├── Center: Active conversation
│   └── Right: Pipeline details
└── Tab 2: Quality Issues (New)
    ├── Left: Project quality list
    ├── Center: Quality dashboard / Chat
    └── Right: Issue details
```

### 7.2 Quality Dashboard Components

```
Quality Issues Dashboard:
├── Summary Cards
│   ├── 🐛 Bugs: Count & Severity
│   ├── 🔒 Vulnerabilities: Count & Severity
│   └── 💩 Code Smells: Count & Effort
├── Issue List (Filterable)
│   ├── Filter by: Type, Severity, Component
│   ├── Sort by: Severity, Effort, File
│   └── Batch selection for fixes
├── Chat Interface
│   ├── Ask about specific issues
│   ├── Request fix explanations
│   └── Discuss best practices
└── Action Panel
    ├── Create Batch MR
    ├── Export Report
    └── View in SonarQube
```

### 7.3 Quality Cards Design

**Issue Summary Card:**
```
┌─ 🔒 Security Vulnerabilities ──────────────────┐
│ Total: 5 issues                                │
│ ──────────────────────────────────────────────│
│ 🔴 Critical: 2 - SQL Injection risks         │
│ 🟡 Major: 3 - Weak cryptography              │
│ ──────────────────────────────────────────────│
│ Estimated effort: 2 hours                     │
│ ──────────────────────────────────────────────│
│ [Fix All Security Issues] [View Details]      │
└────────────────────────────────────────────────┘
```

**Batch Fix Card:**
```
┌─ 🛠️ Batch Fix Proposal ────────────────────────┐
│ Fix 23 Code Smells in One MR                  │
│ ──────────────────────────────────────────────│
│ ✓ Remove 15 unused imports                    │
│ ✓ Fix 5 naming convention issues              │
│ ✓ Simplify 3 complex methods                  │
│ ──────────────────────────────────────────────│
│ Total effort saved: 1.5 hours                 │
│ Files affected: 12                            │
│ ──────────────────────────────────────────────│
│ [Create MR] [Customize Selection] [Preview]   │
└────────────────────────────────────────────────┘
```

## 8. Implementation Plan

### 8.1 Phase 1: Core Quality Infrastructure (Week 1)
- Add webhook endpoint for SonarQube
- Extend database schema
- Create quality session type
- Basic quality analysis tools

### 8.2 Phase 2: Enhanced Analysis (Week 2)
- Implement issue categorization
- Add fix suggestion generation
- Create batch MR functionality
- Integrate with existing vector DB

### 8.3 Phase 3: UI Integration (Week 3)
- Add quality tab to Streamlit
- Implement quality dashboard
- Add chat for quality issues
- Create batch fix interface

### 8.4 Phase 4: Advanced Features (Week 4)
- Quality trends tracking
- Cross-project pattern learning
- Automated fix validation
- Integration with CI/CD pipeline

## 9. Key Differentiators

| Aspect | Pipeline Failures | Quality Issues |
|--------|------------------|----------------|
| Trigger | Build/test failure | Quality gate failure |
| Urgency | Immediate (blocking) | Scheduled (technical debt) |
| Scope | Single failure point | Multiple issues |
| Fix Strategy | One fix per failure | Batch fixes possible |
| Analysis | Log-based | Code-based |
| Session Type | `pipeline` | `quality` |
| UI Tab | Pipeline Failures | Quality Issues |

## 10. Security & Performance Considerations

### 10.1 Security
- Sanitize code snippets in quality fixes
- Validate MR permissions before creation
- Mask sensitive data in quality reports

### 10.2 Performance
- Lazy load quality issues (paginate)
- Cache quality metrics for dashboard
- Batch API calls to SonarQube

## 11. Monitoring & Observability

### 11.1 New Metrics
- Quality gate failure rate by project
- Average issues per quality session
- Batch fix success rate
- Time to resolve quality issues

### 11.2 Alerts
- Repeated quality gate failures
- Security vulnerability threshold exceeded
- Quality session duration limits

---

## 12. References and Resources

### 12.1 Core Technologies
[Previous references remain the same]

### 12.2 Quality Analysis
- **SonarQube Web API**: https://docs.sonarqube.org/latest/extend/web-api/
- **SonarQube Webhooks**: https://docs.sonarqube.org/latest/project-administration/webhooks/

---

## An Important Point to nte is that all logics are to besuch that a decision is taken by LLM, including whihc tools to call, the confidence score should also come from LLM and no where else, no logic is to be harcoded in any manner

**Document Version**: 2.0  
**Last Updated**: 2025-01-27  
**Changes**: Added SonarQube quality gate failure analysis feature

This document serves as the complete technical specification for implementing the CI/CD Pipeline Failure Analysis System with integrated SonarQube quality analysis.