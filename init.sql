-- Create sessions table
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY,
    session_type VARCHAR(20) NOT NULL, -- 'pipeline' or 'quality'
    project_id VARCHAR(255) NOT NULL,
    project_name VARCHAR(255),
    status VARCHAR(20) DEFAULT 'active', -- 'active', 'resolved', 'expired'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '4 hours'),
    
    -- Pipeline specific fields
    pipeline_id VARCHAR(255),
    pipeline_url TEXT,
    branch VARCHAR(255),
    commit_sha VARCHAR(255),
    job_name VARCHAR(255),
    failed_stage VARCHAR(255),
    
    -- Quality specific fields  
    quality_gate_status VARCHAR(20),
    total_issues INTEGER,
    critical_issues INTEGER,
    major_issues INTEGER,
    
    -- Common fields
    conversation_history JSONB DEFAULT '[]',
    webhook_data JSONB DEFAULT '{}',
    merge_request_url TEXT,
    merge_request_id VARCHAR(255),
    fixes_applied JSONB DEFAULT '[]'
);

-- Create indexes
CREATE INDEX idx_sessions_type ON sessions(session_type);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_sessions_project ON sessions(project_id);
CREATE INDEX idx_sessions_created ON sessions(created_at);
CREATE INDEX idx_sessions_expires ON sessions(expires_at);

-- Create updated_at trigger
CREATE OR REPLACE FUNCTION update_last_activity()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_activity = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_sessions_last_activity
BEFORE UPDATE ON sessions
FOR EACH ROW
EXECUTE FUNCTION update_last_activity();