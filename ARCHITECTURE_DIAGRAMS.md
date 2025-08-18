# 🏗️ Complete System Architecture - Single Unified Diagram

## 🎯 AWS Strands Agent Squad CI/CD Failure Analysis System

**What this system does in simple terms:**
- 🔍 Automatically detects when your code builds fail or have quality issues
- 🤖 Uses AI agents to analyze and fix problems intelligently  
- 🔄 Automatically retries fixes up to 3 times with learning
- 📊 Shows progress in a friendly web dashboard
- 🧠 Gets smarter over time by learning from successes and failures

```mermaid
graph TB
    %% External Developer World
    subgraph "👨‍💻 Developer World"
        DEV[🧑‍💻 Developer<br/>Pushes Code]
        IDE[💻 IDE/Local<br/>Development]
        DEV --- IDE
    end
    
    %% External Infrastructure  
    subgraph "🏭 External CI/CD Infrastructure"
        direction TB
        GITLAB[🦊 GitLab<br/>📁 Source Code<br/>🔄 CI/CD Pipelines<br/>🔀 Merge Requests]
        SONAR[📊 SonarQube<br/>🔍 Code Quality Scanner<br/>🚪 Quality Gates<br/>🛡️ Security Analysis]
        
        GITLAB -.->|Quality Scan| SONAR
    end
    
    %% Our System Infrastructure
    subgraph "🤖 Our AI-Powered System"
        direction TB
        
        %% Webhook Layer
        subgraph "📡 Event Detection Layer"
            WH[📡 Webhook Handler<br/>:8000<br/>Always Listening for Problems]
            QUEUE[📥 Event Queue<br/>Process Events]
            WH --> QUEUE
        end
        
        %% Agent Squad Layer  
        subgraph "🧠 AI Agent Squad - The Smart Brain"
            direction TB
            
            SUP[🎯 Supervisor Agent<br/>🧠 Claude 3.5 Sonnet<br/>📋 Intelligent Router<br/>🎪 Coordinates Everything]
            
            subgraph "Specialized Agents"
                direction LR
                PA[🔧 Pipeline Agent<br/>🛠️ Build Expert<br/>- Fix compilation errors<br/>- Resolve dependencies<br/>- Infrastructure setup<br/>- Maven/NPM/Docker issues]
                
                QA[🔍 Quality Agent<br/>🎨 Code Quality Expert<br/>- Fix code smells<br/>- Security vulnerabilities<br/>- SonarQube integration<br/>- Batch fix strategies]
            end
            
            RETRY[🔄 Fix Iteration Handler<br/>♻️ Auto-Retry Coordinator<br/>📊 Pattern Learning<br/>🎯 Smart Re-routing<br/>Max: 3 attempts]
            
            SUP --> PA
            SUP --> QA
            SUP <--> RETRY
            PA --> RETRY
            QA --> RETRY
        end
        
        %% Data Layer
        subgraph "💾 Memory & Learning Layer"
            direction LR
            POSTGRES[(🗄️ PostgreSQL<br/>Session Database<br/>- Conversations<br/>- Fix attempts<br/>- Agent routing history)]
            
            QDRANT[(🧠 Qdrant Vector DB<br/>Learning Memory<br/>- Success patterns<br/>- Error signatures<br/>- AI embeddings)]
        end
        
        %% UI Layer
        subgraph "🖥️ User Interface Layer"
            UI[🖥️ Streamlit Dashboard<br/>:8501<br/>📊 Real-time Updates<br/>💬 Agent Conversations<br/>📈 Progress Tracking]
            
            subgraph "Dashboard Tabs"
                direction LR
                TAB1[🔧 Pipeline Failures<br/>Build Issues & Fixes]
                TAB2[🔍 Quality Issues<br/>Code Quality & Security]
            end
            
            UI --> TAB1
            UI --> TAB2
        end
    end
    
    %% Tool Integration Layer
    subgraph "🔌 Integration Tools (MCP)"
        direction LR
        MCP_GL[🔧 GitLab MCP Tools<br/>- Read pipeline logs<br/>- Create merge requests<br/>- Update comments<br/>- Trigger builds]
        
        MCP_SQ[📊 SonarQube MCP Tools<br/>- Get quality metrics<br/>- Fetch issue details<br/>- Read rule descriptions<br/>- Track trends]
    end
    
    %% Main Flow Connections
    DEV -->|1. Push Code| GITLAB
    GITLAB -->|2. ❌ Build Fails| WH
    SONAR -->|3. ❌ Quality Fails| WH
    
    QUEUE -->|4. Route Problem| SUP
    SUP -->|5a. Build Issue| PA
    SUP -->|5b. Quality Issue| QA
    
    PA -->|6a. Use Tools| MCP_GL
    QA -->|6b. Use Tools| MCP_SQ
    
    MCP_GL <-->|API Calls| GITLAB
    MCP_SQ <-->|API Calls| SONAR
    
    PA -->|7a. Create Fix MR| GITLAB
    QA -->|7b. Create Fix MR| GITLAB
    
    GITLAB -->|8. Test Fix| RETRY
    RETRY -->|9a. ✅ Success| UI
    RETRY -->|9b. ❌ Retry Needed| SUP
    
    %% Data Storage Connections
    SUP <-->|Store Decisions| POSTGRES
    PA <-->|Session Data| POSTGRES
    QA <-->|Session Data| POSTGRES
    RETRY <-->|Attempt History| POSTGRES
    
    PA -->|Learn Patterns| QDRANT
    QA -->|Learn Patterns| QDRANT
    SUP -->|Routing Patterns| QDRANT
    
    %% UI Connections
    UI <-->|Display Sessions| POSTGRES
    UI -->|Show Progress| DEV
    
    %% Webhook Setup (One-time configuration)
    GITLAB -.->|Webhook Config<br/>http://our-system:8000/webhook/gitlab| WH
    SONAR -.->|Webhook Config<br/>http://our-system:8000/webhook/sonarqube| WH
    
    %% Auto-Retry Flow Visualization
    RETRY -.->|Attempt 1/3<br/>Initial Analysis| SUP
    RETRY -.->|Attempt 2/3<br/>Learn & Re-route| SUP  
    RETRY -.->|Attempt 3/3<br/>Final Try| SUP
    RETRY -.->|Max Attempts<br/>Human Help Needed| UI
    
    %% Styling
    classDef developer fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    classDef external fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    classDef webhook fill:#e8f5e8,stroke:#388e3c,stroke-width:2px
    classDef supervisor fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    classDef agents fill:#fce4ec,stroke:#c2185b,stroke-width:2px
    classDef data fill:#e0f2f1,stroke:#00695c,stroke-width:2px
    classDef ui fill:#e1f5fe,stroke:#0277bd,stroke-width:2px
    classDef tools fill:#fff8e1,stroke:#ff8f00,stroke-width:2px
    classDef retry fill:#f1f8e9,stroke:#558b2f,stroke-width:2px
    
    class DEV,IDE developer
    class GITLAB,SONAR external
    class WH,QUEUE webhook
    class SUP supervisor
    class PA,QA agents
    class POSTGRES,QDRANT data
    class UI,TAB1,TAB2 ui
    class MCP_GL,MCP_SQ tools
    class RETRY retry
```

## 🔄 How the Auto-Retry System Works

**Simple Example: "mvn: command not found" in SonarQube**

1. **🔍 Problem Detected**: SonarQube stage fails with "mvn: command not found"
2. **🎯 Supervisor Analysis**: "This is an infrastructure issue, not a quality issue"
3. **🔧 Route to Pipeline Agent**: "You handle build tools and infrastructure"
4. **🛠️ Pipeline Agent Fixes**: Adds Maven to Docker container configuration
5. **🧪 Test the Fix**: GitLab runs the pipeline again
6. **✅ Success or 🔄 Retry**: If it works, celebrate! If not, try a different approach

## 📊 Key System Benefits

| Feature | Description | Benefit |
|---------|-------------|---------|
| **🧠 Intelligent Routing** | Supervisor Agent uses AI to choose the right specialist | Higher success rate than hardcoded rules |
| **🔄 Auto-Retry with Learning** | System tries up to 3 times, learning each time | Handles complex issues that need multiple approaches |
| **🎯 Specialized Agents** | Different AI experts for different problem types | More accurate fixes for specific issue categories |
| **📚 Pattern Learning** | Stores successful solutions in vector database | Gets smarter over time, faster fixes for similar issues |
| **🖥️ Real-time Dashboard** | Live updates on fix progress and agent conversations | Developers stay informed without manual checking |

## 🚀 Container Deployment

```bash
# All services run in Docker containers
docker-compose up -d

# Services and Ports:
# 📡 Webhook Handler:    localhost:8000
# 🤖 Agent Squad:        localhost:8001  
# 🖥️ Streamlit UI:       localhost:8501
# 🗄️ PostgreSQL:         localhost:5432
# 🧠 Qdrant Vector DB:   localhost:6333
```

## 🗄️ Database Schema Architecture

### 📊 PostgreSQL Database Schema

**What we store in PostgreSQL:**
- 💬 Agent conversations and sessions
- 🔄 Fix attempt history and outcomes
- 🎯 Agent routing decisions and performance
- 📈 System metrics and analytics

```mermaid
erDiagram
    sessions ||--o{ messages : contains
    sessions ||--o{ fix_attempts : tracks
    sessions ||--o{ agent_routing : records
    fix_attempts ||--o{ attempt_logs : generates
    agent_routing ||--o{ routing_metrics : measures
    
    sessions {
        uuid id PK "Primary session identifier"
        string session_type "pipeline_failure | quality_failure"
        string project_name "GitLab project name"
        string project_url "GitLab project URL"
        string failure_type "build_error | test_failure | quality_gate"
        text failure_description "Human readable description"
        json failure_context "Raw webhook data + logs"
        string status "active | resolved | failed | abandoned"
        timestamp created_at "When session started"
        timestamp updated_at "Last activity"
        timestamp resolved_at "When issue was fixed"
        int total_attempts "Number of fix attempts"
        string resolved_by_agent "pipeline | quality | human"
        float confidence_score "0.0-1.0 agent confidence"
        text resolution_summary "What fixed the issue"
    }
    
    messages {
        uuid id PK "Message identifier"
        uuid session_id FK "Links to sessions"
        string role "user | assistant | system | tool"
        string agent_type "supervisor | pipeline | quality | system"
        text content "Message content/response"
        json metadata "Tool calls, confidence, etc"
        timestamp created_at "When message was sent"
        int sequence_number "Order in conversation"
        string message_type "analysis | fix_proposal | tool_result"
        json tool_calls "MCP tool invocations"
        json tool_results "Tool execution results"
    }
    
    fix_attempts {
        uuid id PK "Attempt identifier"
        uuid session_id FK "Links to sessions"
        int attempt_number "1, 2, or 3"
        string assigned_agent "pipeline | quality"
        string strategy "compilation_fix | dependency_update | quality_batch"
        text problem_analysis "Agent's understanding of issue"
        text proposed_solution "What the agent plans to do"
        string merge_request_url "GitLab MR created"
        string status "in_progress | testing | success | failed"
        timestamp started_at "When attempt began"
        timestamp completed_at "When attempt finished"
        text failure_reason "Why this attempt failed"
        json performance_metrics "Time taken, tools used, etc"
        float success_probability "Agent's confidence 0.0-1.0"
    }
    
    attempt_logs {
        uuid id PK "Log entry identifier"
        uuid fix_attempt_id FK "Links to fix_attempts"
        string log_level "info | warning | error | debug"
        string component "agent | tool | pipeline | analysis"
        text message "Log message"
        json context "Additional structured data"
        timestamp logged_at "When log was created"
        string correlation_id "For tracing across services"
    }
    
    agent_routing {
        uuid id PK "Routing decision identifier"
        uuid session_id FK "Links to sessions"
        int attempt_number "Which attempt this routing was for"
        string supervisor_reasoning "Why this agent was chosen"
        string selected_agent "pipeline | quality"
        json analysis_factors "What influenced the decision"
        float confidence_score "0.0-1.0 routing confidence"
        timestamp routed_at "When routing decision was made"
        string routing_strategy "llm_analysis | fallback_rules | pattern_match"
        json previous_attempts "Context from earlier attempts"
    }
    
    routing_metrics {
        uuid id PK "Metrics identifier"
        uuid agent_routing_id FK "Links to agent_routing"
        string metric_name "response_time | success_rate | tool_usage"
        float metric_value "Numerical value"
        string metric_unit "seconds | percentage | count"
        json metric_context "Additional metric metadata"
        timestamp measured_at "When metric was recorded"
    }
    
    system_metrics {
        uuid id PK "System metric identifier"
        string metric_type "performance | usage | success_rate"
        string component "webhook_handler | agents | ui | database"
        string metric_name "avg_response_time | sessions_per_hour"
        float value "Metric value"
        string unit "seconds | count | percentage"
        json tags "Component-specific labels"
        timestamp recorded_at "When metric was collected"
        date metric_date "Date for daily aggregations"
    }
    
    webhook_events {
        uuid id PK "Event identifier"
        string source "gitlab | sonarqube"
        string event_type "pipeline_failed | quality_gate_failed"
        text event_payload "Raw webhook JSON"
        uuid session_id FK "Links to sessions (nullable)"
        string processing_status "received | processed | ignored | error"
        text processing_error "Error during processing"
        timestamp received_at "When webhook was received"
        timestamp processed_at "When processing completed"
        string project_identifier "GitLab project ID or SonarQube key"
    }
```

### 🧠 Qdrant Vector Database Schema

**What we store in Qdrant Vector DB:**
- 🎯 Successful fix patterns and strategies
- 🔍 Error signature embeddings for pattern matching
- 📚 Knowledge base of solutions and best practices
- 🧠 Agent learning and experience memories

```mermaid
graph TB
    subgraph "🧠 Qdrant Vector Database Collections"
        
        subgraph "📚 fix_patterns Collection"
            FP1[🎯 Fix Pattern Vectors<br/>📊 Embedding Dimension: 1536<br/>🔢 Distance: Cosine<br/>📝 Indexed: HNSW]
            
            FP_PAYLOAD[📋 Payload Structure:<br/>- fix_strategy: string<br/>- success_count: int<br/>- agent_type: pipeline|quality<br/>- problem_category: string<br/>- solution_code: text<br/>- success_rate: float<br/>- last_used: timestamp<br/>- project_context: json]
        end
        
        subgraph "🔍 error_signatures Collection"
            ES1[🚨 Error Signature Vectors<br/>📊 Embedding Dimension: 1536<br/>🔢 Distance: Cosine<br/>📝 Indexed: HNSW]
            
            ES_PAYLOAD[📋 Payload Structure:<br/>- error_type: string<br/>- error_message_hash: string<br/>- language: java|python|node<br/>- build_tool: maven|npm|pip<br/>- frequency: int<br/>- known_solutions: array<br/>- difficulty_level: easy|medium|hard<br/>- detection_confidence: float]
        end
        
        subgraph "🎓 agent_knowledge Collection"
            AK1[🧠 Agent Knowledge Vectors<br/>📊 Embedding Dimension: 1536<br/>🔢 Distance: Cosine<br/>📝 Indexed: HNSW]
            
            AK_PAYLOAD[📋 Payload Structure:<br/>- knowledge_type: solution|pattern|best_practice<br/>- agent_specialization: pipeline|quality|supervisor<br/>- context_tags: array<br/>- effectiveness_score: float<br/>- usage_count: int<br/>- created_by_session: uuid<br/>- validation_status: verified|experimental<br/>- knowledge_source: agent_learning|manual]
        end
        
        subgraph "📈 success_patterns Collection"
            SP1[✅ Success Pattern Vectors<br/>📊 Embedding Dimension: 1536<br/>🔢 Distance: Cosine<br/>📝 Indexed: HNSW]
            
            SP_PAYLOAD[📋 Payload Structure:<br/>- session_id: uuid<br/>- fix_sequence: array<br/>- time_to_resolution: int<br/>- complexity_factors: json<br/>- replication_success: float<br/>- pattern_stability: float<br/>- environmental_context: json<br/>- learning_value: high|medium|low]
        end
    end
    
    subgraph "🔄 Vector Operations & Workflows"
        
        subgraph "📝 Data Ingestion Flow"
            NEW_SESSION[🆕 New Session] --> EXTRACT[🔍 Extract Features]
            EXTRACT --> EMBED[🧠 Generate Embeddings]
            EMBED --> STORE[💾 Store in Collections]
        end
        
        subgraph "🔍 Similarity Search Flow"
            QUERY[❓ Search Query] --> EMBED_Q[🧠 Embed Query]
            EMBED_Q --> SEARCH[🔍 Vector Search]
            SEARCH --> RANK[📊 Rank Results]
            RANK --> RETURN[📤 Return Matches]
        end
        
        subgraph "📚 Learning & Updates"
            SUCCESS[✅ Successful Fix] --> UPDATE_PATTERNS[📈 Update Success Patterns]
            UPDATE_PATTERNS --> BOOST_SIMILAR[⬆️ Boost Similar Vectors]
            FAILURE[❌ Failed Fix] --> ANALYZE_GAPS[🕳️ Analyze Knowledge Gaps]
            ANALYZE_GAPS --> CREATE_NEW[🆕 Create New Patterns]
        end
    end
    
    %% Collection Relationships
    FP1 -.->|References| SP1
    ES1 -.->|Links to| FP1
    AK1 -.->|Supports| FP1
    SP1 -.->|Validates| AK1
    
    %% Workflow Connections
    STORE -->|fix_patterns| FP1
    STORE -->|error_signatures| ES1
    STORE -->|agent_knowledge| AK1
    STORE -->|success_patterns| SP1
    
    SEARCH -.->|Query| FP1
    SEARCH -.->|Query| ES1
    SEARCH -.->|Query| AK1
    SEARCH -.->|Query| SP1
    
    classDef collection fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    classDef payload fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
    classDef workflow fill:#e8f5e8,stroke:#388e3c,stroke-width:2px
    classDef operation fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    
    class FP1,ES1,AK1,SP1 collection
    class FP_PAYLOAD,ES_PAYLOAD,AK_PAYLOAD,SP_PAYLOAD payload
    class NEW_SESSION,EXTRACT,EMBED,STORE,QUERY,EMBED_Q,SEARCH,RANK,RETURN workflow
    class SUCCESS,UPDATE_PATTERNS,BOOST_SIMILAR,FAILURE,ANALYZE_GAPS,CREATE_NEW operation
```

### 🔗 Database Integration & Data Flow

**How PostgreSQL and Qdrant work together:**

```mermaid
sequenceDiagram
    participant Session as 📝 Session (PostgreSQL)
    participant Agent as 🤖 Agent
    participant Vector as 🧠 Qdrant Vector DB
    participant Knowledge as 📚 Knowledge Store
    
    Note over Session,Knowledge: New Problem Detection
    Session->>Agent: "Build failed with Maven error"
    Agent->>Vector: Search for similar error patterns
    Vector->>Agent: Return top 5 similar cases (90% confidence)
    Agent->>Knowledge: Get detailed solution strategies
    Knowledge->>Agent: Maven dependency fix patterns
    
    Note over Session,Knowledge: Fix Attempt
    Agent->>Session: Store attempt #1 with strategy
    Agent->>Session: Log "Trying dependency update approach"
    Session->>Session: Track attempt progress
    
    Note over Session,Knowledge: Success & Learning
    Agent->>Session: "Fix successful! MR merged"
    Session->>Vector: Store new success pattern
    Vector->>Vector: Update similar pattern weights (+10%)
    Agent->>Vector: Store refined solution strategy
    Vector->>Agent: "Pattern confidence increased to 95%"
    
    Note over Session,Knowledge: Future Speed Improvement
    Session->>Agent: "New similar Maven error"
    Agent->>Vector: Quick pattern match (< 100ms)
    Vector->>Agent: "95% confidence - use dependency strategy"
    Agent->>Session: "Applying proven solution..."
```

### 📊 Database Performance & Scaling

```mermaid
graph TB
    subgraph "🚀 PostgreSQL Performance"
        PG_IDX[📇 Indexes<br/>- session_id (B-tree)<br/>- created_at (B-tree)<br/>- status + session_type (Composite)<br/>- project_name (Hash)]
        
        PG_PART[🗂️ Partitioning<br/>- sessions by month<br/>- messages by session_id<br/>- metrics by date]
        
        PG_CONN[🔗 Connection Pooling<br/>- Max connections: 100<br/>- Pool size: 20<br/>- Async operations]
    end
    
    subgraph "⚡ Qdrant Performance"
        QD_HNSW[🕸️ HNSW Index<br/>- M: 16 (connections)<br/>- ef_construct: 200<br/>- ef: 128 (search)]
        
        QD_SHARD[🔀 Sharding<br/>- 2 shards per collection<br/>- Replication factor: 1<br/>- Load balancing]
        
        QD_CACHE[💾 Vector Cache<br/>- LRU eviction<br/>- Cache size: 512MB<br/>- Hit ratio: >90%]
    end
    
    subgraph "📈 Scaling Strategy"
        HORIZONTAL[↔️ Horizontal Scaling<br/>- Read replicas for PostgreSQL<br/>- Qdrant cluster nodes<br/>- Load balancer routing]
        
        VERTICAL[↕️ Vertical Scaling<br/>- CPU: 4-8 cores<br/>- RAM: 16-32 GB<br/>- SSD: 500GB-1TB]
        
        MONITORING[📊 Monitoring<br/>- Query performance<br/>- Vector search latency<br/>- Storage usage<br/>- Cache hit rates]
    end
    
    classDef postgres fill:#336791,color:#fff
    classDef qdrant fill:#ff6b6b,color:#fff
    classDef scaling fill:#4ecdc4,color:#fff
    
    class PG_IDX,PG_PART,PG_CONN postgres
    class QD_HNSW,QD_SHARD,QD_CACHE qdrant
    class HORIZONTAL,VERTICAL,MONITORING scaling
```

---

*This unified diagram shows the complete AWS Strands Agent Squad architecture for intelligent CI/CD failure analysis and auto-remediation. The system combines multiple AI agents, pattern learning, and auto-retry capabilities to automatically fix build failures and code quality issues.*
