-- CI/CD Assistant Database Schema

-- Sessions table for tracking analysis sessions
CREATE TABLE IF NOT EXISTS sessions (
    id VARCHAR(255) PRIMARY KEY,
    session_type VARCHAR(50) NOT NULL,
    project_id VARCHAR(255),
    project_name VARCHAR(255),
    pipeline_id VARCHAR(255),
    pipeline_status VARCHAR(50),
    pipeline_url TEXT,
    job_name VARCHAR(255),
    job_id VARCHAR(255),
    branch VARCHAR(255),
    failed_stage VARCHAR(255),
    commit_sha VARCHAR(255),
    sonarqube_key VARCHAR(255),
    quality_gate_status VARCHAR(50),
    mr_id VARCHAR(255),
    mr_title TEXT,
    mr_url TEXT,
    unique_id VARCHAR(255), -- For preventing duplicate sessions (pipeline_id for GitLab, project_key:branch for SonarQube)
    conversation_history JSONB DEFAULT '[]',
    webhook_data JSONB DEFAULT '{}',
    analysis_result JSONB DEFAULT '{}',
    fixes_applied JSONB DEFAULT '[]',
    status VARCHAR(50) DEFAULT 'active',
    subscription_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '60 minutes')
);

-- Webhook subscriptions table
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    subscription_id VARCHAR(255) PRIMARY KEY,
    project_id VARCHAR(255) NOT NULL,
    project_type VARCHAR(50) NOT NULL,
    project_url TEXT,
    webhook_url TEXT,
    webhook_secret VARCHAR(255),
    webhook_ids JSONB DEFAULT '[]',
    webhook_events JSONB DEFAULT '[]',
    access_token TEXT,
    api_key VARCHAR(255),
    metadata JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_refreshed TIMESTAMP,
    expires_at TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '90 days')
);

-- Fix attempts tracking
CREATE TABLE IF NOT EXISTS fix_attempts (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) REFERENCES sessions(id),
    attempt_number INTEGER,
    branch_name VARCHAR(255),
    merge_request_id VARCHAR(255),
    merge_request_url TEXT,
    status VARCHAR(50),
    error_message TEXT,
    files_changed JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Messages table for conversation history
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) REFERENCES sessions(id),
    role VARCHAR(50),
    content TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Vector store metadata (tracks what's stored in OpenSearch)
CREATE TABLE IF NOT EXISTS vector_store_entries (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255),
    project_id VARCHAR(255),
    entry_type VARCHAR(50),
    opensearch_doc_id VARCHAR(255),
    summary TEXT,
    success BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_sessions_project_id ON sessions(project_id);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX idx_sessions_subscription ON sessions(subscription_id);
CREATE INDEX idx_sessions_unique_id ON sessions(unique_id);
CREATE INDEX idx_sessions_type_project_unique ON sessions(session_type, project_id, unique_id);
CREATE INDEX idx_sessions_pipeline_lookup ON sessions(session_type, project_id, pipeline_id) WHERE session_type = 'pipeline';

CREATE INDEX idx_subscriptions_project ON webhook_subscriptions(project_id);
CREATE INDEX idx_subscriptions_status ON webhook_subscriptions(status);
CREATE INDEX idx_subscriptions_expires ON webhook_subscriptions(expires_at);
CREATE INDEX idx_subscriptions_api_key ON webhook_subscriptions(api_key);

CREATE INDEX idx_fix_attempts_session ON fix_attempts(session_id);
CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_vector_entries_project ON vector_store_entries(project_id);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
CREATE TRIGGER update_sessions_updated_at BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_subscriptions_updated_at BEFORE UPDATE ON webhook_subscriptions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();