-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Drop existing tables if they exist (for clean setup)
DROP TABLE IF EXISTS agent_feedback CASCADE;
DROP TABLE IF EXISTS historical_fixes CASCADE;
DROP TABLE IF EXISTS quality_fixes CASCADE;
DROP TABLE IF EXISTS quality_issues CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;

-- Sessions table (updated with quality analysis fields)
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
    interaction_type VARCHAR(50), -- suggestion, fix_applied, user_feedback
    interaction_data JSONB,
    outcome VARCHAR(20), -- helpful, not_helpful, partially_helpful
    feedback_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_sessions_project_id ON sessions(project_id);
CREATE INDEX idx_sessions_pipeline_id ON sessions(pipeline_id);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX idx_sessions_type ON sessions(session_type);
CREATE INDEX idx_sessions_created_at ON sessions(created_at);
CREATE INDEX idx_quality_issues_session ON quality_issues(session_id);
CREATE INDEX idx_quality_issues_type ON quality_issues(issue_type);
CREATE INDEX idx_quality_issues_severity ON quality_issues(severity);
CREATE INDEX idx_historical_fixes_signature ON historical_fixes(error_signature_hash);

-- Function to update last_activity
CREATE OR REPLACE FUNCTION update_last_activity()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_activity = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update last_activity
DROP TRIGGER IF EXISTS update_session_activity ON sessions;
CREATE TRIGGER update_session_activity
BEFORE UPDATE ON sessions
FOR EACH ROW
EXECUTE FUNCTION update_last_activity();

-- Grant permissions (adjust as needed for your database user)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO cicd_user;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO cicd_user;