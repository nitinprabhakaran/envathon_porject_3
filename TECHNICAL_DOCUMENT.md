# CI/CD Pipeline Failure Analysis System - Technical Design Document

## 1. System Overview

### 1.1 Purpose
An intelligent CI/CD pipeline failure analysis system that automatically diagnoses GitLab pipeline failures AND SonarQube quality gate failures, provides actionable fixes through AWS Strands Agent Squad pattern, and maintains conversational context with intelligent auto-retry capabilities.

### 1.2 Key Components
- **GitLab Webhook Integration**: Receives pipeline failure notifications
- **SonarQube Webhook Integration**: Receives quality gate failure notifications  
- **AWS Strands Agent Squad**: Intelligent agent coordination with supervisor-based routing
  - **Supervisor Agent**: Routes failures to specialized agents using AWS Strands intelligence
  - **Pipeline Agent**: Handles build, test, deployment, and infrastructure failures
  - **Quality Agent**: Handles code quality, security, and SonarQube issues
- **Fix Iteration Handler**: Intelligent auto-retry system with failure pattern learning
- **Session Management**: Persistent conversation state with PostgreSQL
- **Vector Knowledge Base**: Historical error patterns and solutions using Qdrant
- **MCP Integration**: GitLab and SonarQube tools integrated into agent container
- **Streamlit UI**: Interactive dashboard with adaptive response cards and multi-tab interface

### 1.3 Technology Stack
- **Agent Framework**: AWS Strands Agents SDK (Model-driven intelligent routing)
- **LLM**: Claude 3.5 Sonnet via Bedrock/Anthropic
- **Agent Pattern**: AWS Agent Squad with Supervisor delegation
- **MCP Servers**: GitLab MCP + SonarQube MCP (integrated)
- **Database**: PostgreSQL (sessions) + Qdrant (vectors)
- **UI**: Streamlit with adaptive cards and tabbed interface
- **Deployment**: Docker Compose

## 2. AWS Strands Agent Squad Architecture

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
               │ - Create/Get ID (session_type determined by Supervisor) │
               │ - Context Loading & Fix Iteration Tracking             │
               └─────────┬───────────────────────────────────┬───────────┘
                        │                                    │
          ┌─────────────┴─────────────┐                     │
          ▼                           ▼                     │
┌─────────────────┐         ┌─────────────────┐            │
│   PostgreSQL    │         │     Qdrant      │            │
│   (Sessions +   │         │  (Vector DB)    │            │
│  Fix Attempts)  │         │ Error Patterns  │            │
└─────────────────┘         └─────────────────┘            │
                                                            │
                        ▼                                   ▼
          ┌─────────────────────────────────────────────────────────────┐
          │              AWS Strands Agent Squad Container                │
          │  ┌─────────────────────────────────────────────────────┐   │
          │  │              🎯 SUPERVISOR AGENT                    │   │
          │  │          (Intelligent Failure Routing)             │   │
          │  │  ┌─────────┐  ┌─────────┐  ┌─────────────────┐   │   │
          │  │  │  LLM-   │  │  Rule-  │  │ Fix Iteration   │   │   │
          │  │  │ Based   │  │ Based   │  │    Handler      │   │   │
          │  │  │Analysis │  │Fallback │  │   Integration   │   │   │
          │  │  └─────────┘  └─────────┘  └─────────────────┘   │   │
          │  └─────────────────┬───────────────────────────────────┘   │
          │                    │                                       │
          │                    ▼                                       │
          │  ┌─────────────────────────────────────────────────────┐   │
          │  │           🔧 PIPELINE AGENT                         │   │
          │  │  ➤ Build failures        ➤ Infrastructure issues   │   │
          │  │  ➤ Test failures         ➤ Deployment problems     │   │
          │  │  ➤ Compilation errors    ➤ Tool configuration      │   │
          │  │  ➤ Dependency issues     ➤ CI/CD environment       │   │
          │  └─────────────────────────────────────────────────────┘   │
          │                             │                               │
          │  ┌─────────────────────────────────────────────────────┐   │
          │  │           🔍 QUALITY AGENT                          │   │
          │  │  ➤ SonarQube issues      ➤ Security vulnerabilities│   │
          │  │  ➤ Code quality rules    ➤ Code coverage           │   │
          │  │  ➤ Maintainability       ➤ Reliability rating      │   │
          │  │  ➤ Code smells           ➤ Quality gate failures   │   │
          │  └─────────────────────────────────────────────────────┘   │
          │                                                             │
          │  ┌─────────────────────────────────────────────────────┐   │
          │  │                 MCP TOOL LAYER                      │   │
          │  │  ┌─────────────────┐  ┌─────────────────────────┐   │   │
          │  │  │  GitLab MCP     │  │    SonarQube MCP        │   │   │
          │  │  │  Tools          │  │    Tools                │   │   │
          │  │  └─────────────────┘  └─────────────────────────┘   │   │
          │  └─────────────────────────────────────────────────────┘   │
          └─────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
               ┌─────────────────────────────────────────────────────────┐
               │                    Streamlit UI                         │
               │  ┌─────────────────────────────────────────────────┐   │
               │  │ Tab 1: Pipeline Failures │ Tab 2: Quality Issues │   │
               │  ├─────────────────────────────────────────────────┤   │
               │  │ - Auto-retry Status      │ - Quality Dashboard  │   │
               │  │ - Fix Attempt History    │ - Issue Categories   │   │
               │  │ - Agent Routing Logs     │ - Batch Fix Options  │   │
               │  │ - Session Context        │ - Agent Analysis     │   │
               │  └─────────────────────────────────────────────────┘   │
               └─────────────────────────────────────────────────────────┘
```

### 2.2 Intelligent Agent Routing Flow

```
Pipeline/Quality Gate Failure Detected
                    │
                    ▼
            ┌─────────────────┐
            │ Fix Iteration   │
            │    Handler      │
            │ ──────────────  │
            │ 1. Check retry  │
            │ 2. Analyze logs │
            │ 3. Route agent  │
            └─────────┬───────┘
                    │
                    ▼
            ┌─────────────────┐
            │ 🎯 SUPERVISOR   │
            │    AGENT        │
            │ ──────────────  │
            │ AWS Strands     │
            │ Intelligence    │
            └─────────┬───────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
┌─────────────┐ ┌─────────┐ ┌─────────────┐
│LLM Analysis │ │Pipeline │ │Rule-based   │
│"Quality     │ │Context  │ │Fallback     │
│keywords     │ │Analysis │ │Classification│
│detected"    │ │         │ │             │
└─────────────┘ └─────────┘ └─────────────┘
        │           │           │
        └───────────┼───────────┘
                    ▼
        ┌─────────────────────────┐
        │    AGENT SELECTION      │
        │ ─────────────────────── │
        │ Quality Issues  →  🔍   │
        │ Build Failures  →  🔧   │
        │ Infrastructure  →  🔧   │
        │ Mixed Problems  →  🎯   │
        └─────────────────────────┘
                    │
                    ▼
        ┌─────────────────────────┐
        │   SPECIALIZED AGENT     │
        │    EXECUTION            │
        │ ─────────────────────── │
        │ - Context-aware         │
        │ - Tool selection        │
        │ - Fix generation        │
        │ - Confidence scoring    │
        └─────────────────────────┘
```

### 2.3 Fix Iteration & Auto-Retry System

```
Fix Attempt Workflow:
┌─────────────────────────────────────────────────────────────────┐
│                    Initial Failure Detected                     │
└─────────────────────┬───────────────────────────────────────────┘
                    │
                    ▼
          ┌─────────────────────┐     Max Attempts
          │ Fix Iteration       │◄────Reached (3)
          │ Handler             │         │
          │ ─────────────────── │         ▼
          │ Attempt: 1/3        │ ┌─────────────┐
          │ Agent: Supervisor   │ │ Session     │
          │ Analysis: Initial   │ │ Terminated  │
          └─────────┬───────────┘ │ Status: Max │
                    │             │ Attempts    │
                    ▼             └─────────────┘
          ┌─────────────────────┐
          │ Supervisor Routes   │
          │ to Specialized      │
          │ Agent (Pipeline/    │
          │ Quality)            │
          └─────────┬───────────┘
                    │
                    ▼
          ┌─────────────────────┐
          │ Agent Generates     │
          │ Fix & Creates MR    │
          └─────────┬───────────┘
                    │
                    ▼
          ┌─────────────────────┐
          │ Webhook Monitors    │     Fix Failed
          │ MR Pipeline         │◄────(Pipeline fails)
          └─────────┬───────────┘         │
                    │                     │
            Fix Succeeded                 │
                    │                     │
                    ▼                     │
          ┌─────────────────────┐         │
          │ Session Success     │         │
          │ Pattern Learning    │         │
          │ Vector Storage      │         │
          └─────────────────────┘         │
                                         │
    ┌──────────────────────────────────────┘
    │
    ▼
┌─────────────────────┐     
│ Fix Iteration       │     
│ Handler             │     
│ ─────────────────── │     
│ Attempt: 2/3        │     
│ Context: Previous   │     
│ failure patterns    │     
│ Agent: Re-analyzed  │     
│ by Supervisor       │     
└─────────┬───────────┘     
          │
          ▼
┌─────────────────────┐
│ Enhanced Analysis   │
│ - Previous errors   │
│ - Recurring patterns│
│ - New approach      │
│ - Agent re-routing  │
└─────────────────────┘
```

### 2.4 Container Architecture with Agent Squad

```
Docker Compose Services:
┌─────────────────────────────────────────────────────────────────┐
│                        External Services                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │   GitLab    │  │  SonarQube  │  │ PostgreSQL  │             │
│  │ (External)  │  │ (External)  │  │             │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
└─────────────────────────────────────────────────────────────────┘
                                    │
┌─────────────────────────────────────────────────────────────────┐
│                    Internal Services Stack                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │   Qdrant    │  │  Webhook    │  │ Streamlit   │             │
│  │ Vector DB   │  │  Handler    │  │     UI      │             │
│  │             │  │             │  │  (Tabbed)   │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │             AWS Strands Agent Squad                     │   │
│  │ ┌─────────────────────────────────────────────────────┐ │   │
│  │ │ 🎯 supervisor_agent.py                              │ │   │
│  │ │ ├─ Intelligent routing logic                        │ │   │
│  │ │ ├─ LLM-based analysis                               │ │   │
│  │ │ ├─ Rule-based fallback                              │ │   │
│  │ │ └─ Session continuity management                    │ │   │
│  │ └─────────────────────────────────────────────────────┘ │   │
│  │                          │                             │   │
│  │ ┌─────────────────────────┼─────────────────────────┐   │   │
│  │ │ 🔧 pipeline_agent.py    │  🔍 quality_agent.py    │   │   │
│  │ │ ├─ Build failures       │  ├─ SonarQube issues    │   │   │
│  │ │ ├─ Test failures        │  ├─ Code quality        │   │   │
│  │ │ ├─ Infrastructure       │  ├─ Security vulns      │   │   │
│  │ │ └─ Deployment issues    │  └─ Quality gates       │   │   │
│  │ └─────────────────────────┴─────────────────────────┘   │   │
│  │                                                         │   │
│  │ ┌─────────────────────────────────────────────────────┐ │   │
│  │ │           Fix Iteration Handler                     │ │   │
│  │ │ ├─ Auto-retry coordination                          │ │   │
│  │ │ ├─ Failure pattern analysis                         │ │   │
│  │ │ ├─ Supervisor integration                           │ │   │
│  │ │ └─ Session state management                         │ │   │
│  │ └─────────────────────────────────────────────────────┘ │   │
│  │                                                         │   │
│  │ ┌─────────────────────────────────────────────────────┐ │   │
│  │ │                 MCP Tool Layer                      │ │   │
│  │ │  ┌─────────────────┐  ┌─────────────────────────┐   │ │   │
│  │ │  │  GitLab MCP     │  │    SonarQube MCP        │   │ │   │
│  │ │  │  - Projects     │  │    - Quality gates      │   │ │   │
│  │ │  │  - Pipelines    │  │    - Issues             │   │ │   │
│  │ │  │  - MRs          │  │    - Metrics            │   │ │   │
│  │ │  │  - Commits      │  │    - Rules              │   │ │   │
│  │ │  └─────────────────┘  └─────────────────────────┘   │ │   │
│  │ └─────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 3. Intelligent Agent Decision Flow

### 3.1 Supervisor Agent Decision Matrix

```
┌─────────────────────────────────────────────────────────────────┐
│                    🎯 SUPERVISOR AGENT                          │
│                   Intelligent Routing                           │
└─────────────────────┬───────────────────────────────────────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  Failure Analysis   │
          │  Input Processing   │
          └─────────┬───────────┘
                   │
                   ▼
     ┌─────────────────────────────────────┐
     │         Decision Matrix              │
     │ ──────────────────────────────────── │
     │ Error Keywords Analysis:             │
     │ ├─ "sonar", "quality" → 🔍 Quality  │
     │ ├─ "build", "compile"  → 🔧 Pipeline │
     │ ├─ "mvn not found"     → 🔧 Pipeline │
     │ ├─ "test failed"       → 🔧 Pipeline │
     │ └─ "vulnerabilities"   → 🔍 Quality  │
     │                                     │
     │ Stage Analysis:                     │
     │ ├─ "quality_stage"     → 🔍 Quality │
     │ ├─ "build_stage"       → 🔧 Pipeline │
     │ ├─ "test_stage"        → 🔧 Pipeline │
     │ └─ "deploy_stage"      → 🔧 Pipeline │
     │                                     │
     │ Context Analysis:                   │
     │ ├─ Pipeline logs       → 🔧 Pipeline │
     │ ├─ SonarQube webhook   → 🔍 Quality  │
     │ ├─ Infrastructure errs → 🔧 Pipeline │
     │ └─ Mixed indicators    → 🎯 Re-route │
     └─────────────────────────────────────┘
                   │
                   ▼
     ┌─────────────────────────────────────┐
     │         Agent Delegation            │
     │ ──────────────────────────────────── │
     │ Quality Issues (30%):               │
     │ └─ quality_agent.analyze_failure()  │
     │                                     │
     │ Pipeline Issues (65%):              │
     │ └─ pipeline_agent.analyze_failure() │
     │                                     │
     │ Complex Issues (5%):                │
     │ └─ supervisor_agent.coordinate()    │
     └─────────────────────────────────────┘
```

### 3.2 Infrastructure vs Application Classification

```
Infrastructure Issues (→ Pipeline Agent):
┌─────────────────────────────────────────┐
│ 🔧 Pipeline Agent Handles:              │
│ ├─ mvn: command not found               │
│ ├─ docker: command not found            │
│ ├─ npm: command not found               │
│ ├─ java: command not found              │
│ ├─ python: command not found            │
│ ├─ git: command not found               │
│ ├─ Build tool configuration             │
│ ├─ CI/CD environment setup              │
│ ├─ Missing dependencies                 │
│ ├─ Permission denied errors             │
│ ├─ Network connectivity issues          │
│ ├─ Container runtime problems           │
│ └─ Deployment configuration             │
└─────────────────────────────────────────┘

Quality Issues (→ Quality Agent):
┌─────────────────────────────────────────┐
│ 🔍 Quality Agent Handles:               │
│ ├─ SonarQube quality gate failures      │
│ ├─ Code coverage below threshold        │
│ ├─ Security vulnerabilities detected    │
│ ├─ Code smells and maintainability      │
│ ├─ Reliability rating issues            │
│ ├─ Duplicate code detection             │
│ ├─ Complex method warnings              │
│ ├─ Unused import statements             │
│ ├─ Naming convention violations         │
│ ├─ Security hotspots                    │
│ └─ Technical debt accumulation          │
└─────────────────────────────────────────┘
```

## 4. Data Flow Architecture with Intelligent Routing

### 4.1 Enhanced Pipeline Failure Flow

```
GitLab Pipeline Failure Detected
        │
        ▼
Webhook → POST /webhook/gitlab
        │
        ▼
┌───────────────────────┐
│ Webhook Processor     │
│ 1. Parse pipeline data│
│ 2. Extract error logs │
│ 3. Create session ID  │
└───────┬───────────────┘
        │
        ▼
┌───────────────────────┐
│ Fix Iteration Handler │
│ 1. Check retry count  │
│ 2. Analyze patterns   │
│ 3. Enhanced logging   │
└───────┬───────────────┘
        │
        ▼
┌───────────────────────┐
│ Session Manager       │
│ 1. Store in DB        │
│ 2. Track attempts     │
│ 3. Set 4hr expiry     │
└───────┬───────────────┘
        │
        ▼
┌───────────────────────┐
│ 🎯 Supervisor Agent   │
│ 1. Analyze failure    │
│ 2. Classify issue     │
│ 3. Route to agent     │
│ 4. Monitor progress   │
└───────┬───────────────┘
        │
     ┌──┴──┐
     ▼     ▼
┌─────────┐ ┌─────────┐
│🔧 Pipeline│ │🔍 Quality│
│ Agent   │ │ Agent   │
│Analysis │ │Analysis │
└─────────┘ └─────────┘
     │         │
     └────┬────┘
          ▼
┌───────────────────────┐
│ Fix Generation        │
│ 1. Context-aware      │
│ 2. Tool selection     │
│ 3. MR creation        │
│ 4. Auto-monitoring    │
└───────┬───────────────┘
        │
        ▼
┌───────────────────────┐
│ Auto-Retry System     │
│ 1. Monitor MR pipeline│
│ 2. Detect new failure │
│ 3. Re-route if needed │
│ 4. Learn patterns     │
└───────────────────────┘
```

### 4.2 SonarQube Quality Gate Flow with Supervisor

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
│ 2. Extract issues     │
│ 3. Create session ID  │
└───────┬───────────────┘
        │
        ▼
┌───────────────────────┐
│ 🎯 Supervisor Agent   │
│ 1. Quality gate       │
│ 2. Issue analysis     │
│ 3. Route to quality   │
│ 4. Batch strategy     │
└───────┬───────────────┘
        │
        ▼
┌───────────────────────┐
│ 🔍 Quality Agent      │
│ 1. SonarQube MCP      │
│ 2. Issue categorization│
│ 3. Fix prioritization │
│ 4. Batch solutions    │
└───────┬───────────────┘
        │
        ▼
┌───────────────────────┐
│ Response Formatter    │
│ 1. Quality dashboard  │
│ 2. Issue cards        │
│ 3. Batch MR option    │
│ 4. Learning feedback  │
└───────┬───────────────┘
        │
        ▼
Quality Analysis Dashboard
```

### 4.3 Fix Iteration with Intelligent Re-routing

```
Fix Attempt Fails (Auto-Retry Flow):
┌─────────────────────────────────────────────────────┐
│                Pipeline MR Failed                    │
└─────────────────┬───────────────────────────────────┘
                 │
                 ▼
        ┌─────────────────┐
        │ Fix Iteration   │
        │ Handler         │
        │ ──────────────  │
        │ 1. Record fail  │
        │ 2. Analyze new  │
        │ 3. Check retry  │
        │ 4. Re-route     │
        └─────────┬───────┘
                 │
                 ▼
        ┌─────────────────┐
        │ Enhanced        │      Previous Agent: 🔧 Pipeline
        │ Pattern         │      New Error Type: Quality issues
        │ Analysis        │      ─────────────────────────────
        │ ──────────────  │      Decision: Re-route to 🔍 Quality
        │ - Previous errs │      
        │ - New patterns  │      Previous Agent: 🔍 Quality
        │ - Context shift │      New Error Type: Infrastructure
        │ - Agent fitness │      ─────────────────────────────
        └─────────┬───────┘      Decision: Re-route to 🔧 Pipeline
                 │
                 ▼
        ┌─────────────────┐
        │ 🎯 Supervisor   │
        │ Re-evaluation   │
        │ ──────────────  │
        │ "Should we try  │
        │ a different     │
        │ specialist?"    │
        └─────────┬───────┘
                 │
    ┌────────────┼────────────┐
    ▼            ▼            ▼
┌─────────┐ ┌─────────┐ ┌─────────┐
│Same     │ │Different│ │Complex  │
│Agent    │ │Agent    │ │Multi-   │
│Retry    │ │Route    │ │Agent    │
└─────────┘ └─────────┘ └─────────┘
    │            │            │
    └────────────┼────────────┘
                 ▼
        ┌─────────────────┐
        │ Adaptive Fix    │
        │ Generation      │
        │ ──────────────  │
        │ - New approach  │
        │ - Agent context │
        │ - Learning      │
        │ - Confidence    │
        └─────────────────┘
```

## 5. Database Design (Enhanced for Agent Squad)

### 5.1 PostgreSQL Schema (Updated with Auto-Retry & Agent Tracking)

```sql
-- Sessions table (enhanced with agent tracking)
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id VARCHAR(255) NOT NULL,
    pipeline_id VARCHAR(255),  -- Nullable for quality sessions
    session_type VARCHAR(20) DEFAULT 'pipeline', -- 'pipeline' or 'quality'
    commit_hash VARCHAR(40),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '4 hours'),
    status VARCHAR(50) DEFAULT 'active', -- active, resolved, abandoned, retrying, max_attempts_reached
    
    -- Agent tracking (NEW)
    current_agent VARCHAR(20), -- supervisor, pipeline, quality
    agent_routing_history JSONB DEFAULT '[]', -- Track agent switches
    confidence_scores JSONB DEFAULT '{}', -- LLM confidence per attempt
    
    -- Fix iteration tracking (NEW)
    fix_attempts JSONB DEFAULT '[]', -- Array of fix attempt objects
    current_attempt INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    last_failure_analysis JSONB DEFAULT '{}',
    
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

-- Fix attempts table (NEW - detailed tracking)
CREATE TABLE fix_attempts (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    agent_type VARCHAR(20) NOT NULL, -- supervisor, pipeline, quality
    
    -- Failure analysis
    error_patterns TEXT[],
    failure_context JSONB,
    pipeline_analysis JSONB, -- Enhanced log analysis
    
    -- Fix strategy
    fix_strategy TEXT,
    confidence_score FLOAT, -- LLM-generated confidence
    tools_used TEXT[],
    
    -- Outcome tracking
    mr_url TEXT,
    mr_status VARCHAR(20), -- proposed, merged, failed
    pipeline_result VARCHAR(20), -- success, failed, pending
    
    -- Timing
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    duration_seconds INTEGER,
    
    -- Learning data
    was_successful BOOLEAN,
    failure_reason TEXT,
    lessons_learned TEXT
);

-- Agent routing log (NEW - for analysis & debugging)
CREATE TABLE agent_routing_log (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    from_agent VARCHAR(20), -- NULL for initial routing
    to_agent VARCHAR(20) NOT NULL,
    
    -- Routing decision context
    routing_reason TEXT, -- LLM or rule-based reason
    decision_confidence FLOAT,
    error_patterns TEXT[],
    stage_context VARCHAR(100),
    
    -- Routing method
    routing_method VARCHAR(20), -- llm, rule_based, fallback
    supervisor_analysis JSONB, -- Full supervisor reasoning
    
    -- Timing
    routed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Outcome tracking
    routing_successful BOOLEAN, -- Did this routing lead to success?
    feedback TEXT
);

-- Quality issues table (enhanced)
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
    
    -- AI-generated fix data
    suggested_fix TEXT,
    fix_confidence FLOAT, -- LLM confidence in fix
    fix_approach VARCHAR(50), -- batch, individual, ignore
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Quality fixes table (enhanced)
CREATE TABLE quality_fixes (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    attempt_id INTEGER REFERENCES fix_attempts(id),
    
    issue_ids TEXT[], -- Array of issue IDs being fixed
    fix_type VARCHAR(50), -- batch, individual, priority
    fix_category VARCHAR(50), -- security, maintainability, reliability
    
    -- Fix strategy
    agent_strategy TEXT, -- LLM-generated strategy
    estimated_effort INTEGER, -- minutes
    priority_score FLOAT, -- LLM-calculated priority
    
    -- Implementation
    mr_url TEXT,
    status VARCHAR(20), -- proposed, applied, merged, failed
    
    -- Results
    issues_resolved INTEGER,
    new_issues_introduced INTEGER,
    quality_improvement FLOAT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_sessions_project_id ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(current_agent);
CREATE INDEX IF NOT EXISTS idx_sessions_attempts ON sessions(current_attempt);
CREATE INDEX IF NOT EXISTS idx_fix_attempts_session ON fix_attempts(session_id);
CREATE INDEX IF NOT EXISTS idx_fix_attempts_agent ON fix_attempts(agent_type);
CREATE INDEX IF NOT EXISTS idx_routing_log_session ON agent_routing_log(session_id);
CREATE INDEX IF NOT EXISTS idx_routing_log_agents ON agent_routing_log(from_agent, to_agent);
```

### 5.2 Vector Database Collections (Enhanced for Agent Learning)

```yaml
# Enhanced collections for agent squad pattern learning

agent_routing_patterns:
  description: "Successful agent routing decisions and outcomes"
  vector_size: 1536
  payload_schema:
    error_patterns: array
    from_agent: string
    to_agent: string
    success_rate: float
    context_keywords: array
    confidence_threshold: float
    routing_reason: string

fix_iteration_patterns:
  description: "Multi-attempt fix patterns and learning"
  vector_size: 1536
  payload_schema:
    initial_error: string
    attempt_sequence: array  # [agent1, agent2, agent3]
    final_success: boolean
    total_attempts: integer
    success_factors: array
    failure_patterns: array
    project_context: object

supervisor_decisions:
  description: "Supervisor agent reasoning and outcomes"
  vector_size: 1536
  payload_schema:
    decision_context: string
    routing_choice: string
    confidence_score: float
    outcome_success: boolean
    learning_feedback: string
    error_classification: string

quality_patterns:
  description: "Quality issue patterns and agent fixes"
  vector_size: 1536
  payload_schema:
    issue_type: string
    severity: string
    rule_key: string
    fix_pattern: string
    agent_confidence: float
    success_rate: float
    effort_saved: integer

pipeline_patterns:
  description: "Pipeline failure patterns and agent solutions"
  vector_size: 1536
  payload_schema:
    failure_type: string
    infrastructure_issue: boolean
    build_context: string
    fix_approach: string
    agent_tools_used: array
    resolution_time: integer
```

## 6. AWS Strands Agent Squad Implementation

### 6.1 Enhanced Agent Architecture

```
AWS Strands Agent Squad Container:
├── 🎯 Supervisor Agent (supervisor_agent.py)
│   ├── Core Intelligence
│   │   ├── @tool analyze_with_pipeline_agent()
│   │   ├── @tool analyze_with_quality_agent()
│   │   ├── @tool check_session_continuity()
│   │   └── coordinate_failure_analysis()
│   ├── LLM Decision Engine
│   │   ├── Model: Claude 3.5 Sonnet
│   │   ├── System prompt: Routing specialist
│   │   ├── Context: Failure analysis
│   │   └── Output: Agent delegation
│   └── Fallback Logic
│       ├── Rule-based classification
│       ├── Error pattern matching
│       └── Historical routing data
│
├── 🔧 Pipeline Agent (pipeline_agent.py)
│   ├── Specialized Tools
│   │   ├── @tool analyze_build_logs()
│   │   ├── @tool check_dependencies()
│   │   ├── @tool diagnose_test_failures()
│   │   ├── @tool fix_infrastructure_issues()
│   │   └── @tool create_pipeline_fix_mr()
│   ├── Infrastructure Expertise
│   │   ├── Build tool configuration (mvn, gradle, npm)
│   │   ├── Container/Docker issues
│   │   ├── CI/CD environment setup
│   │   ├── Dependency resolution
│   │   └── Deployment configuration
│   └── Application Issues
│       ├── Compilation errors
│       ├── Test failures
│       ├── Integration issues
│       └── Performance problems
│
├── 🔍 Quality Agent (quality_agent.py)
│   ├── SonarQube Integration
│   │   ├── @tool analyze_quality_gate()
│   │   ├── @tool get_quality_issues_by_type()
│   │   ├── @tool suggest_quality_fixes()
│   │   ├── @tool create_batch_quality_mr()
│   │   └── @tool prioritize_quality_issues()
│   ├── Issue Categories
│   │   ├── Security vulnerabilities
│   │   ├── Reliability bugs
│   │   ├── Maintainability code smells
│   │   ├── Coverage thresholds
│   │   └── Code complexity
│   └── Fix Strategies
│       ├── Batch fixes for similar issues
│       ├── Priority-based fixing
│       ├── Quick wins identification
│       └── Technical debt management
│
└── 🔄 Fix Iteration Handler (fix_iteration_handler.py)
    ├── Auto-Retry Logic
    │   ├── handle_fix_branch_failure()
    │   ├── _trigger_automatic_retry()
    │   ├── _determine_failure_agent_type()
    │   └── _analyze_pipeline_logs_for_context()
    ├── Supervisor Integration
    │   ├── Uses supervisor for agent routing
    │   ├── Tracks agent switches per attempt
    │   ├── Learns from routing decisions
    │   └── Adapts strategy based on patterns
    └── Pattern Learning
        ├── Recurring error detection
        ├── Fix effectiveness tracking
        ├── Agent performance analysis
        └── Success pattern storage
```

### 6.2 Supervisor Agent Decision Flow

```
🎯 Supervisor Agent Analysis Process:

1. CONTEXT GATHERING
   ┌─────────────────────────────────────┐
   │ Input Analysis                      │
   │ ├─ Webhook data examination         │
   │ ├─ Error pattern extraction         │
   │ ├─ Pipeline context analysis        │
   │ ├─ Historical session data          │
   │ └─ Previous attempt context         │
   └─────────────────────────────────────┘
                   │
                   ▼
2. INTELLIGENT CLASSIFICATION
   ┌─────────────────────────────────────┐
   │ LLM-Based Analysis                  │
   │ ├─ Error semantic understanding     │
   │ ├─ Context-aware classification     │
   │ ├─ Tool requirement assessment      │
   │ ├─ Confidence score generation      │
   │ └─ Routing recommendation           │
   └─────────────────────────────────────┘
                   │
                   ▼
3. FALLBACK MECHANISMS
   ┌─────────────────────────────────────┐
   │ Rule-Based Classification           │
   │ ├─ Keyword pattern matching         │
   │ ├─ Stage-based routing              │
   │ ├─ Historical success patterns      │
   │ └─ Default safe routing             │
   └─────────────────────────────────────┘
                   │
                   ▼
4. AGENT DELEGATION
   ┌─────────────────────────────────────┐
   │ Specialized Agent Invocation        │
   │ ├─ Context preparation              │
   │ ├─ Tool provisioning                │
   │ ├─ Session state management         │
   │ └─ Progress monitoring              │
   └─────────────────────────────────────┘
```

### 6.3 Agent Routing Examples

```
Example Routing Decisions:

┌─ SonarQube "mvn: command not found" ──────────────────────┐
│ Input: SonarQube stage failed with script failure        │
│ ────────────────────────────────────────────────────────│
│ 🎯 Supervisor Analysis:                                  │
│ ├─ Keywords: "mvn", "command not found"                 │
│ ├─ Context: SonarQube stage                             │
│ ├─ Classification: Infrastructure issue                  │
│ ├─ LLM Reasoning: "Missing build tool configuration"    │
│ └─ Decision: Route to 🔧 Pipeline Agent                 │
│ ────────────────────────────────────────────────────────│
│ ✅ Result: Pipeline Agent fixes Maven configuration      │
└──────────────────────────────────────────────────────────┘

┌─ Quality Gate Failure ────────────────────────────────────┐
│ Input: SonarQube quality gate ERROR status              │
│ ────────────────────────────────────────────────────────│
│ 🎯 Supervisor Analysis:                                  │
│ ├─ Keywords: "quality", "vulnerabilities", "code_smell" │
│ ├─ Context: Quality gate webhook                        │
│ ├─ Classification: Code quality issue                   │
│ ├─ LLM Reasoning: "Quality standards violation"         │
│ └─ Decision: Route to 🔍 Quality Agent                  │
│ ────────────────────────────────────────────────────────│
│ ✅ Result: Quality Agent batches fixes for issues       │
└──────────────────────────────────────────────────────────┘

┌─ Build Compilation Error ─────────────────────────────────┐
│ Input: Java compilation errors in build stage           │
│ ────────────────────────────────────────────────────────│
│ 🎯 Supervisor Analysis:                                  │
│ ├─ Keywords: "compilation", "build", "java"             │
│ ├─ Context: Build stage failure                         │
│ ├─ Classification: Application code issue               │
│ ├─ LLM Reasoning: "Source code compilation problem"     │
│ └─ Decision: Route to 🔧 Pipeline Agent                 │
│ ────────────────────────────────────────────────────────│
│ ✅ Result: Pipeline Agent fixes code syntax errors      │
└──────────────────────────────────────────────────────────┘

┌─ Complex Mixed Issue ─────────────────────────────────────┐
│ Input: Build succeeds but quality gate fails            │
│ ────────────────────────────────────────────────────────│
│ 🎯 Supervisor Analysis:                                  │
│ ├─ Keywords: Mixed indicators                           │
│ ├─ Context: Multi-stage failure                         │
│ ├─ Classification: Sequential issue handling            │
│ ├─ LLM Reasoning: "Quality issues after build success"  │
│ └─ Decision: Route to 🔍 Quality Agent (primary)        │
│ ────────────────────────────────────────────────────────│
│ ✅ Result: Quality Agent handles post-build issues      │
└──────────────────────────────────────────────────────────┘
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

## 7. Streamlit UI Design (Enhanced with Agent Visibility)

### 7.1 UI Architecture - Tabbed Interface with Agent Tracking

```
Streamlit Application (Enhanced with Agent Squad Visibility):
├── Header (Global Navigation)
│   ├── 🎯 Agent Squad Status Dashboard
│   │   ├─ Active Sessions by Agent
│   │   ├─ Success Rate by Agent Type
│   │   ├─ Current Routing Statistics
│   │   └─ Auto-Retry Progress
│   └── Tab selector with badges
│
├── Tab 1: Pipeline Failures (Enhanced)
│   ├── Left Panel: Pipeline List
│   │   ├─ Session cards with agent badges
│   │   ├─ Auto-retry status indicators
│   │   ├─ Attempt counter (1/3, 2/3, 3/3)
│   │   └─ Agent routing history
│   ├── Center Panel: Active Conversation
│   │   ├─ Agent identification headers
│   │   ├─ Routing decision explanations
│   │   ├─ Confidence score displays
│   │   └─ Auto-retry notifications
│   └── Right Panel: Enhanced Pipeline Details
│       ├─ Agent routing logs
│       ├─ Fix attempt timeline
│       ├─ Error pattern analysis
│       └─ Infrastructure alerts
│
└── Tab 2: Quality Issues (Enhanced)
    ├── Left Panel: Project Quality List
    │   ├─ Quality session cards
    │   ├─ Agent assignment status
    │   ├─ Batch fix progress
    │   └─ SonarQube gate status
    ├── Center Panel: Quality Dashboard / Chat
    │   ├─ Agent conversation interface
    │   ├─ Issue categorization display
    │   ├─ Fix confidence indicators
    │   └─ Batch operation status
    └── Right Panel: Detailed Issue Analysis
        ├─ Issue breakdown by agent
        ├─ Fix strategy explanations
        ├─ Quality improvement metrics
        └─ Agent performance tracking
```

### 7.2 Agent Status Dashboard Components

```
🎯 Agent Squad Status Dashboard:
┌─────────────────────────────────────────────────────────────┐
│ Agent Squad Performance Overview                            │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐            │
│ │🎯 Supervisor│ │🔧 Pipeline  │ │🔍 Quality   │            │
│ │ Active: 3   │ │ Active: 12  │ │ Active: 8   │            │
│ │ Success: 95%│ │ Success: 78%│ │ Success: 85%│            │
│ └─────────────┘ └─────────────┘ └─────────────┘            │
├─────────────────────────────────────────────────────────────┤
│ Auto-Retry Status:                                          │
│ ├─ 🔄 Active retries: 5                                    │
│ ├─ ✅ Successful auto-fixes today: 23                       │
│ ├─ ❌ Max attempts reached: 2                               │
│ └─ 📊 Average attempts to success: 1.8                     │
├─────────────────────────────────────────────────────────────┤
│ Routing Intelligence:                                       │
│ ├─ 🧠 LLM routing decisions: 78%                           │
│ ├─ 📋 Rule-based fallbacks: 22%                            │
│ ├─ 🔄 Agent re-routing events: 12                          │
│ └─ 🎯 Routing accuracy: 89%                                │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 Enhanced Session Cards with Agent Context

```
Pipeline Session Card (Enhanced):
┌─ 🔧 Pipeline Session #abc123 ─────────────────────────────────┐
│ Project: envathon-java | Branch: feature/new-auth           │
│ ──────────────────────────────────────────────────────────── │
│ 🎯 Supervisor → 🔧 Pipeline Agent                            │
│ ├─ Initial routing: Build failure detected                   │
│ ├─ Confidence: 92%                                          │
│ └─ Route reason: "Maven compilation errors"                  │
│ ──────────────────────────────────────────────────────────── │
│ Auto-Retry Status: Attempt 2/3 🔄                           │
│ ├─ Attempt 1: Failed - missing dependency                   │
│ ├─ Attempt 2: In progress - added missing deps              │
│ └─ Next: Auto-trigger if this fails                         │
│ ──────────────────────────────────────────────────────────── │
│ 🕐 Started: 14:30 | ⏱️ Duration: 12min | 📊 Tools: 8        │
│ ──────────────────────────────────────────────────────────── │
│ [View Conversation] [Agent Logs] [Retry History]            │
└──────────────────────────────────────────────────────────────┘

Quality Session Card (Enhanced):
┌─ � Quality Session #def456 ─────────────────────────────────┐
│ Project: envathon-web | SonarQube: quality-gate-failed      │
│ ──────────────────────────────────────────────────────────── │
│ 🎯 Supervisor → 🔍 Quality Agent                             │
│ ├─ Initial routing: SonarQube webhook received              │
│ ├─ Confidence: 98%                                          │
│ └─ Route reason: "Quality gate ERROR status"                │
│ ──────────────────────────────────────────────────────────── │
│ Issues Overview:                                            │
│ ├─ 🔴 Critical: 3 security vulnerabilities                 │
│ ├─ 🟡 Major: 12 code smells                                │
│ └─ 🔵 Minor: 45 maintainability issues                     │
│ ──────────────────────────────────────────────────────────── │
│ Batch Fix Status: Ready for creation 🎯                     │
│ ├─ Security fixes: High priority                            │
│ ├─ Code smells: Batch processing                            │
│ └─ Estimated effort: 2.5 hours                              │
│ ──────────────────────────────────────────────────────────── │
│ [Create Batch MR] [View Issues] [Quality Dashboard]         │
└──────────────────────────────────────────────────────────────┘
```

### 7.4 Agent Routing History Display

```
Agent Routing Timeline:
┌─────────────────────────────────────────────────────────────┐
│ � Session #abc123 - Agent Routing History                  │
├─────────────────────────────────────────────────────────────┤
│ 🕐 14:30:15 | 🎯 Supervisor Agent                           │
│ ├─ Analyzing failure context...                             │
│ ├─ Keywords detected: "maven", "compilation", "build"       │
│ ├─ LLM Analysis: "Build infrastructure issue detected"      │
│ └─ Decision: Route to Pipeline Agent (confidence: 92%)      │
├─────────────────────────────────────────────────────────────┤
│ 🕐 14:30:22 | 🔧 Pipeline Agent                             │
│ ├─ Tools used: analyze_build_logs, check_dependencies       │
│ ├─ Fix strategy: "Add missing Maven dependency"             │
│ ├─ MR created: !123 "Fix missing junit dependency"         │
│ └─ Result: MR pipeline failed (attempt 1/3)                 │
├─────────────────────────────────────────────────────────────┤
│ 🕐 14:45:30 | 🔄 Fix Iteration Handler                      │
│ ├─ Retry triggered automatically                            │
│ ├─ New error analysis: "SonarQube quality issues"          │
│ ├─ Pattern change detected: Infrastructure → Quality        │
│ └─ Re-routing recommended to Supervisor                      │
├─────────────────────────────────────────────────────────────┤
│ 🕐 14:45:35 | 🎯 Supervisor Agent (Re-evaluation)           │
│ ├─ Context: Previous fix succeeded, new quality issues      │
│ ├─ LLM Analysis: "Quality gate failure after build fix"    │
│ ├─ Decision: Route to Quality Agent (confidence: 89%)       │
│ └─ Reason: "SonarQube integration detected"                 │
├─────────────────────────────────────────────────────────────┤
│ 🕐 14:45:42 | 🔍 Quality Agent                              │
│ ├─ Tools used: analyze_quality_gate, get_project_issues     │
│ ├─ Strategy: "Batch fix for code smells and security"       │
│ ├─ Issues found: 15 total (3 critical, 12 major)           │
│ └─ Status: Creating comprehensive fix MR...                  │
└─────────────────────────────────────────────────────────────┘
```

## 8. Implementation Plan (Updated for Agent Squad)

### 8.1 Phase 1: Agent Squad Foundation (Week 1)
- ✅ **Supervisor Agent Enhancement**
  - Implement LLM-based routing decisions
  - Add rule-based fallback mechanisms  
  - Create agent delegation tools
  - Integrate with fix iteration handler

- ✅ **Fix Iteration Handler Refactoring**
  - Remove hardcoded infrastructure logic
  - Integrate supervisor agent routing
  - Enhance pipeline log analysis
  - Add auto-retry with intelligent re-routing

- 📋 **Database Schema Updates**
  - Add agent tracking tables
  - Implement fix attempts logging
  - Create routing decision history
  - Add confidence score storage

### 8.2 Phase 2: Agent Intelligence Enhancement (Week 2)
- 📋 **Pipeline Agent Specialization**
  - Enhance infrastructure issue handling
  - Improve build failure analysis
  - Add dependency resolution tools
  - Integrate container/Docker support

- 📋 **Quality Agent Enhancement** 
  - Expand SonarQube integration
  - Implement batch fix strategies
  - Add security vulnerability handling
  - Create quality trend analysis

- 📋 **Vector Learning Integration**
  - Store agent routing patterns
  - Learn from successful delegations
  - Track agent performance metrics
  - Implement pattern matching

### 8.3 Phase 3: UI & Monitoring Integration (Week 3)
- 📋 **Streamlit UI Enhancement**
  - Add agent status dashboard
  - Implement routing history display
  - Create agent performance metrics
  - Add auto-retry progress tracking

- 📋 **Monitoring & Observability**
  - Agent performance dashboards
  - Routing decision analytics
  - Success rate tracking per agent
  - Auto-retry effectiveness metrics

### 8.4 Phase 4: Advanced Learning & Optimization (Week 4)
- 📋 **Advanced Agent Coordination**
  - Multi-agent collaboration scenarios
  - Complex issue routing strategies
  - Cross-agent learning patterns
  - Predictive routing capabilities

- 📋 **Performance Optimization**
  - Agent response time optimization
  - Parallel processing capabilities
  - Caching strategies
  - Resource utilization monitoring

## 9. Key Architecture Improvements

### 9.1 Before vs After Comparison

| Aspect | Previous Architecture | New Agent Squad Architecture |
|--------|----------------------|------------------------------|
| **Routing Logic** | Hardcoded rules in fix handler | AWS Strands Supervisor with LLM intelligence |
| **Agent Types** | Single agent + artificial "infrastructure" | Specialized Pipeline & Quality agents |
| **Decision Making** | Rule-based classification | Model-driven with intelligent fallback |
| **Infrastructure Issues** | Separate agent category | Handled by Pipeline agent (correct routing) |
| **Auto-Retry** | Fixed logic | Supervisor re-evaluation per attempt |
| **Learning** | Limited pattern storage | Full agent performance tracking |
| **Scalability** | Monolithic agent | Modular specialist agents |
| **Maintainability** | Complex hardcoded logic | Clean delegation pattern |

### 9.2 Agent Routing Accuracy Improvements

```
SonarQube "mvn: command not found" Issue:
────────────────────────────────────────────
❌ Old: Infrastructure Agent (doesn't exist)
✅ New: Pipeline Agent (correct - infrastructure setup)

Quality Gate Failures:
────────────────────────────────────────────
❌ Old: Hardcoded quality detection
✅ New: Supervisor LLM analysis → Quality Agent

Build + Quality Issues:
────────────────────────────────────────────
❌ Old: Fixed routing, no re-evaluation
✅ New: Dynamic re-routing based on failure context

Mixed Infrastructure + Code Issues:
────────────────────────────────────────────
❌ Old: Either/or classification
✅ New: Sequential handling via supervisor coordination
```

### 9.3 AWS Strands Compliance Features

| AWS Strands Principle | Implementation |
|----------------------|----------------|
| **Model-Driven Decisions** | Supervisor uses LLM for routing, not hardcoded rules |
| **Intelligent Tool Selection** | Agents select tools based on context and confidence |
| **Conversational Context** | Full session state maintained across agent switches |
| **Learning & Adaptation** | Vector storage of successful routing patterns |
| **Confidence Scoring** | LLM-generated confidence for all agent decisions |
| **Fallback Mechanisms** | Rule-based routing when LLM unavailable |
| **Agent Specialization** | Clear separation of concerns between agents |
| **Delegation Patterns** | Supervisor orchestrates specialist coordination |

## 10. Monitoring & Observability (Enhanced)

### 10.1 Agent Performance Metrics

```yaml
Agent Squad Metrics:
├── Supervisor Agent
│   ├── Routing accuracy rate
│   ├── LLM vs rule-based decisions ratio
│   ├── Re-routing frequency
│   └── Decision confidence scores
├── Pipeline Agent  
│   ├── Infrastructure issue resolution rate
│   ├── Build failure fix success rate
│   ├── Average resolution time
│   └── Tool usage patterns
├── Quality Agent
│   ├── Quality gate improvement rate
│   ├── Batch fix effectiveness
│   ├── Security issue resolution time
│   └── Code quality trend impact
└── Fix Iteration System
    ├── Auto-retry success rate
    ├── Average attempts to resolution
    ├── Pattern learning effectiveness
    └── Agent switch accuracy
```

### 10.2 Alert Conditions (Enhanced)

```yaml
Agent Squad Alerts:
├── Performance Alerts
│   ├── Agent success rate below 70%
│   ├── Routing accuracy below 80%
│   ├── Auto-retry failure rate above 20%
│   └── Average resolution time exceeding SLA
├── Intelligence Alerts  
│   ├── LLM routing failures increasing
│   ├── Confidence scores trending down
│   ├── Fallback routing usage above 30%
│   └── Agent re-routing frequency spike
├── Operational Alerts
│   ├── Max attempts reached repeatedly
│   ├── Session timeout rate increase
│   ├── Agent tool failures
│   └── Vector learning pipeline issues
└── Quality Alerts
    ├── Recurring infrastructure issues
    ├── Quality degradation trends
    ├── Security vulnerability accumulation
    └── Technical debt growth rate
```

---

## 11. References and Resources

### 11.1 Core Technologies
- **AWS Strands Agents SDK**: https://github.com/strands-agents/sdk-python
- **AWS Strands Documentation**: https://strandsagents.com/
- **AWS Agent Squad Patterns**: https://docs.aws.amazon.com/bedrock/latest/userguide/agents-squad.html
- **Claude 3.5 Sonnet**: https://www.anthropic.com/claude
- **PostgreSQL**: https://www.postgresql.org/
- **Qdrant Vector Database**: https://qdrant.tech/
- **Streamlit**: https://streamlit.io/

### 11.2 MCP Integration
- **GitLab MCP Server**: https://github.com/nguyenvanduocit/gitlab-mcp
- **SonarQube MCP Server**: https://github.com/sonarsource/sonarqube-mcp-server
- **Model Context Protocol**: https://modelcontextprotocol.io/

### 11.3 Quality Analysis
- **SonarQube Web API**: https://docs.sonarqube.org/latest/extend/web-api/
- **SonarQube Webhooks**: https://docs.sonarqube.org/latest/project-administration/webhooks/
- **GitLab CI/CD**: https://docs.gitlab.com/ee/ci/

### 11.4 Agent Squad Architecture Patterns
- **Supervisor Agent Design**: AWS Strands coordination patterns
- **Specialized Agent Communication**: Inter-agent delegation
- **Fix Iteration Patterns**: Auto-retry with intelligent routing
- **Vector Learning Systems**: Pattern storage and retrieval

---

## 12. Architecture Decision Records (ADRs)

### 12.1 ADR-001: Supervisor Agent Pattern
**Decision**: Use AWS Strands Supervisor Agent for intelligent routing instead of hardcoded logic  
**Context**: Original implementation had hardcoded rules for determining agent type  
**Consequences**: 
- ✅ Model-driven decision making
- ✅ Intelligent routing based on context
- ✅ Fallback mechanisms for reliability
- ✅ Better scalability for new agent types

### 12.2 ADR-002: No Infrastructure Agent
**Decision**: Route infrastructure issues to Pipeline Agent instead of creating separate agent  
**Context**: SonarQube "mvn: command not found" should go to Pipeline Agent, not separate infrastructure agent  
**Consequences**:
- ✅ Simpler architecture with two specialized agents
- ✅ Pipeline Agent handles both application and infrastructure issues
- ✅ Cleaner separation of concerns (build vs quality)
- ✅ Easier maintenance and debugging

### 12.3 ADR-003: LLM-First Decision Making
**Decision**: Use LLM analysis for all agent routing decisions with rule-based fallback  
**Context**: AWS Strands emphasizes model-driven intelligence over hardcoded rules  
**Consequences**:
- ✅ Context-aware intelligent routing
- ✅ Learning and adaptation capabilities
- ✅ High-quality decision explanations
- ✅ Graceful degradation when LLM unavailable

### 12.4 ADR-004: Fix Iteration with Re-routing
**Decision**: Allow agent re-routing between fix attempts based on failure pattern changes  
**Context**: Initial agent choice may not be optimal after seeing fix results  
**Consequences**:
- ✅ Adaptive problem-solving approach
- ✅ Higher success rates through agent flexibility
- ✅ Learning from routing effectiveness
- ✅ Better handling of complex multi-faceted issues

---

## 🎯 Critical Success Factors

### 🔑 AWS Strands Compliance Principles

> **"All logic decisions are to be made by LLM, including which tools to call. The confidence score should also come from LLM and nowhere else. No logic is to be hardcoded in any manner."**

This architecture strictly adheres to this principle through:

1. **🧠 LLM-Driven Routing**: Supervisor Agent uses Claude 3.5 Sonnet for all routing decisions
2. **🎯 Confidence Scoring**: All confidence scores generated by LLM, not algorithmic calculations  
3. **🔧 Tool Selection**: Agents use LLM to select appropriate tools based on context
4. **📊 Pattern Learning**: Vector storage of LLM-analyzed patterns, not rule-based classifications
5. **🔄 Adaptive Routing**: Re-routing decisions based on LLM analysis of changed contexts
6. **🛡️ Fallback Transparency**: Even rule-based fallbacks are LLM-inspired and clearly marked

### 🎨 Architecture Elegance

```
┌─────────────────────────────────────────────────────────────┐
│ 🎯 AWS Strands Agent Squad - Intelligent CI/CD Analysis     │
│                                                            │
│ Pipeline/Quality Failure → 🎯 Supervisor (LLM Analysis)    │
│                          ↓                                │
│         🔧 Pipeline Agent ←→ 🔍 Quality Agent               │
│                          ↓                                │
│              Intelligent Fix Generation                    │
│                          ↓                                │
│           Auto-Retry with Adaptive Routing                │
│                          ↓                                │
│            Success with Learning Storage                   │
└─────────────────────────────────────────────────────────────┘
```

---

**Document Version**: 3.0 - AWS Strands Agent Squad Architecture  
**Last Updated**: August 18, 2025  
**Major Changes**: 
- Implemented AWS Strands Supervisor Agent pattern
- Removed hardcoded infrastructure agent logic
- Added intelligent routing with LLM-based decisions
- Enhanced auto-retry system with adaptive re-routing
- Added comprehensive agent performance tracking

This document serves as the complete technical specification for the AWS Strands Agent Squad implementation of the CI/CD Pipeline Failure Analysis System with intelligent supervisor routing and specialized agent coordination.