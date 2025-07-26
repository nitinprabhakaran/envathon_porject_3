-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Sessions table
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id VARCHAR(255) NOT NULL,
    pipeline_id VARCHAR(255) NOT NULL,
    commit_hash VARCHAR(40),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '4 hours'),
    status VARCHAR(50) DEFAULT 'active',
    
    -- Failure context
    failed_stage VARCHAR(100),
    error_type VARCHAR(100),
    error_signature TEXT,
    logs_summary TEXT,
    
    -- Conversation data
    conversation_history JSONB DEFAULT '[]',
    applied_fixes JSONB DEFAULT '[]',
    successful_fixes JSONB DEFAULT '[]',
    
    -- Metadata
    tokens_used INTEGER DEFAULT 0,
    tools_called JSONB DEFAULT '[]',
    user_feedback JSONB DEFAULT '{}'
);

-- Historical fixes table
CREATE TABLE historical_fixes (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    error_signature_hash VARCHAR(64),
    fix_description TEXT,
    fix_type VARCHAR(50),
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success_confirmed BOOLEAN,
    confidence_score FLOAT,
    project_context JSONB
);

-- Learning feedback table
CREATE TABLE agent_feedback (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    interaction_type VARCHAR(50),
    interaction_data JSONB,
    outcome VARCHAR(20),
    feedback_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_sessions_project_id ON sessions(project_id);
CREATE INDEX idx_sessions_pipeline_id ON sessions(pipeline_id);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX idx_historical_fixes_signature ON historical_fixes(error_signature_hash);
CREATE INDEX idx_historical_fixes_project ON historical_fixes(project_context);

-- Function to update last_activity
CREATE OR REPLACE FUNCTION update_last_activity()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_activity = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update last_activity
CREATE TRIGGER update_session_activity
BEFORE UPDATE ON sessions
FOR EACH ROW
EXECUTE FUNCTION update_last_activity();