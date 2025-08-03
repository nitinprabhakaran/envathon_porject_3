-- Create sessions table with all fields including quality metrics
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY,
    session_type VARCHAR(20) NOT NULL,
    project_id VARCHAR(255) NOT NULL,
    project_name VARCHAR(255),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
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
    fixes_applied JSONB DEFAULT '[]',
    
    -- Fix tracking fields
    current_fix_branch VARCHAR(255),
    fix_iteration INTEGER DEFAULT 0,
    parent_session_id UUID  -- NEW FIELD
);

-- Add foreign key constraint for parent_session_id
ALTER TABLE sessions 
ADD CONSTRAINT fk_parent_session 
FOREIGN KEY (parent_session_id) 
REFERENCES sessions(id) 
ON DELETE SET NULL;

-- Create tracked files table for better file management
CREATE TABLE IF NOT EXISTS tracked_files (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    original_content TEXT,
    tracked_content TEXT,
    status VARCHAR(20) NOT NULL, -- 'success', 'not_found', 'error'
    tracked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}',
    UNIQUE(session_id, file_path)
);

-- Create fix attempts table for tracking iterations
CREATE TABLE IF NOT EXISTS fix_attempts (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    branch_name VARCHAR(255) NOT NULL,
    merge_request_id VARCHAR(255),
    merge_request_url TEXT,
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'success', 'failed'
    files_changed JSONB DEFAULT '[]',
    error_details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    UNIQUE(session_id, attempt_number)
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
CREATE INDEX IF NOT EXISTS idx_sessions_fix_branch ON sessions(current_fix_branch);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);  -- NEW INDEX
CREATE INDEX IF NOT EXISTS idx_tracked_files_session ON tracked_files(session_id);
CREATE INDEX IF NOT EXISTS idx_tracked_files_path ON tracked_files(session_id, file_path);
CREATE INDEX IF NOT EXISTS idx_fix_attempts_session ON fix_attempts(session_id, attempt_number);
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

-- Add migration for existing sessions
DO $$
BEGIN
    -- Add columns if they don't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'sessions' AND column_name = 'current_fix_branch') THEN
        ALTER TABLE sessions ADD COLUMN current_fix_branch VARCHAR(255);
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'sessions' AND column_name = 'fix_iteration') THEN
        ALTER TABLE sessions ADD COLUMN fix_iteration INTEGER DEFAULT 0;
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'sessions' AND column_name = 'parent_session_id') THEN
        ALTER TABLE sessions ADD COLUMN parent_session_id UUID;
        ALTER TABLE sessions ADD CONSTRAINT fk_parent_session 
        FOREIGN KEY (parent_session_id) REFERENCES sessions(id) ON DELETE SET NULL;
    END IF;
END $$;