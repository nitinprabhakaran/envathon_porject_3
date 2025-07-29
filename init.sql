-- Create sessions table with all fields including quality metrics
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
    error_signature TEXT,
    
    -- Quality specific fields  
    quality_gate_status VARCHAR(20),
    total_issues INTEGER DEFAULT 0,
    critical_issues INTEGER DEFAULT 0,
    major_issues INTEGER DEFAULT 0,
    bug_count INTEGER DEFAULT 0,
    vulnerability_count INTEGER DEFAULT 0,
    code_smell_count INTEGER DEFAULT 0,
    coverage DECIMAL(5,2),
    duplicated_lines_density DECIMAL(5,2),
    reliability_rating VARCHAR(1),
    security_rating VARCHAR(1),
    maintainability_rating VARCHAR(1),
    
    -- Common fields
    conversation_history JSONB DEFAULT '[]',
    webhook_data JSONB DEFAULT '{}',
    merge_request_url TEXT,
    merge_request_id VARCHAR(255),
    fixes_applied JSONB DEFAULT '[]'
);

-- Create historical fixes table
CREATE TABLE IF NOT EXISTS historical_fixes (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    error_signature_hash VARCHAR(64),
    fix_description TEXT,
    fix_type VARCHAR(50),
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success_confirmed BOOLEAN DEFAULT FALSE,
    confidence_score FLOAT,
    project_context JSONB
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(session_type);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_quality_gate ON sessions(quality_gate_status);
CREATE INDEX IF NOT EXISTS idx_historical_fixes_signature ON historical_fixes(error_signature_hash);
CREATE INDEX IF NOT EXISTS idx_historical_fixes_session ON historical_fixes(session_id);

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