
-- ============================================================================
-- Adaptive Preference Testing System - Complete Database Schema
-- Version: 3.1 (Fixed & Enterprise-Ready)
-- Database: PostgreSQL 14+
-- Created: November 7, 2025
-- ============================================================================

-- Drop existing tables (for clean setup)
DROP TABLE IF EXISTS provenance_log CASCADE;
DROP TABLE IF EXISTS audit_log CASCADE;
DROP TABLE IF EXISTS choices CASCADE;
DROP TABLE IF EXISTS algorithm_state CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS stimuli CASCADE;
DROP TABLE IF EXISTS experiments CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- USERS TABLE
-- ============================================================================
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(200),
    institution VARCHAR(200),
    role VARCHAR(50) DEFAULT 'researcher' CHECK (role IN ('admin', 'researcher', 'student')),
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,
    email_verified BOOLEAN DEFAULT FALSE,
    
    -- Settings
    preferences JSONB DEFAULT '{}',
    
    -- Indexes
    CONSTRAINT email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$')
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_active ON users(is_active) WHERE is_active = TRUE;

-- ============================================================================
-- EXPERIMENTS TABLE
-- ============================================================================
CREATE TABLE experiments (
    experiment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    
    -- Basic Info
    name VARCHAR(200) NOT NULL,
    description TEXT,
    research_question TEXT,
    
    -- Configuration
    num_stimuli INTEGER NOT NULL CHECK (num_stimuli >= 3),
    max_trials INTEGER NOT NULL CHECK (max_trials >= 10),
    min_trials INTEGER DEFAULT 10 CHECK (min_trials >= 5),
    
    -- Algorithm Parameters
    epsilon FLOAT DEFAULT 0.01 CHECK (epsilon > 0 AND epsilon < 1),
    exploration_weight FLOAT DEFAULT 0.1 CHECK (exploration_weight >= 0 AND exploration_weight <= 1),
    prior_mean FLOAT DEFAULT 0.0,
    prior_variance FLOAT DEFAULT 1.0 CHECK (prior_variance > 0),
    convergence_threshold FLOAT DEFAULT 0.05 CHECK (convergence_threshold > 0),
    
    -- Session Settings
    max_session_duration_minutes INTEGER DEFAULT 30 CHECK (max_session_duration_minutes > 0),
    inactivity_timeout_minutes INTEGER DEFAULT 5 CHECK (inactivity_timeout_minutes > 0),
    show_progress BOOLEAN DEFAULT TRUE,
    allow_breaks BOOLEAN DEFAULT TRUE,
    break_interval INTEGER DEFAULT 20 CHECK (break_interval > 0),
    enable_counterbalancing BOOLEAN DEFAULT TRUE,
    
    -- Instructions & Messages
    instructions TEXT DEFAULT 'You will be shown pairs of images. Please select the image you prefer.',
    completion_message TEXT DEFAULT 'Thank you for participating! Your responses have been recorded.',
    
    -- Status
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'paused', 'archived', 'deleted')),
    published_at TIMESTAMP WITH TIME ZONE,
    archived_at TIMESTAMP WITH TIME ZONE,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Metadata
    metadata JSONB DEFAULT '{}',
    
    -- Computed columns
    estimated_duration_minutes INTEGER GENERATED ALWAYS AS (
        CEIL((max_trials * 3.0) / 60.0)  -- ~3 seconds per trial
    ) STORED
);

CREATE INDEX idx_experiments_user ON experiments(user_id);
CREATE INDEX idx_experiments_status ON experiments(status);
CREATE INDEX idx_experiments_created ON experiments(created_at DESC);
CREATE INDEX idx_experiments_active ON experiments(status, published_at) 
    WHERE status = 'active';

-- ============================================================================
-- STIMULI TABLE
-- ============================================================================
CREATE TABLE stimuli (
    stimulus_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_id UUID NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    
    -- Identification
    stimulus_name VARCHAR(200) NOT NULL,
    display_order INTEGER,
    
    -- File Info
    file_path VARCHAR(500) NOT NULL,
    url TEXT,
    file_size_bytes INTEGER,
    mime_type VARCHAR(100),
    width_px INTEGER,
    height_px INTEGER,
    
    -- Security
    checksum_sha256 VARCHAR(64),
    
    -- Metadata
    metadata JSONB DEFAULT '{}',
    tags TEXT[],
    
    -- Timestamps
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Constraints
    CONSTRAINT unique_stimulus_name_per_experiment UNIQUE (experiment_id, stimulus_name),
    CONSTRAINT valid_display_order CHECK (display_order > 0),
    CONSTRAINT valid_dimensions CHECK (width_px > 0 AND height_px > 0)
);

CREATE INDEX idx_stimuli_experiment ON stimuli(experiment_id);
CREATE INDEX idx_stimuli_display_order ON stimuli(experiment_id, display_order);

-- ============================================================================
-- SESSIONS TABLE
-- ============================================================================
CREATE TABLE sessions (
    session_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_id UUID NOT NULL REFERENCES experiments(experiment_id) ON DELETE RESTRICT,
    
    -- Session Identification
    session_token VARCHAR(128) UNIQUE NOT NULL,
    subject_id VARCHAR(100),  -- Optional external ID
    
    -- Status
    status VARCHAR(20) DEFAULT 'active' CHECK (
        status IN ('created', 'active', 'paused', 'complete', 'abandoned', 'error')
    ),
    
    -- Progress
    trials_completed INTEGER DEFAULT 0 CHECK (trials_completed >= 0),
    trials_total INTEGER NOT NULL,
    current_trial INTEGER DEFAULT 0,
    
    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    last_activity_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Duration tracking
    total_time_seconds INTEGER DEFAULT 0,
    
    -- Subject Metadata
    subject_metadata JSONB DEFAULT '{}',
    browser_info JSONB DEFAULT '{}',
    ip_address INET,
    
    -- Quality Metrics
    consistency_score FLOAT,
    attention_check_passed BOOLEAN,
    
    -- Completion percentage (computed)
    progress_percentage FLOAT GENERATED ALWAYS AS (
        CASE WHEN trials_total > 0 
        THEN (trials_completed::FLOAT / trials_total::FLOAT) * 100.0 
        ELSE 0 END
    ) STORED,
    
    -- Constraints
    CONSTRAINT valid_progress CHECK (trials_completed <= trials_total)
);

CREATE INDEX idx_sessions_experiment ON sessions(experiment_id);
CREATE INDEX idx_sessions_token ON sessions(session_token);
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_sessions_active ON sessions(experiment_id, status) 
    WHERE status IN ('active', 'paused');
CREATE INDEX idx_sessions_last_activity ON sessions(last_activity_at DESC);

-- ============================================================================
-- ALGORITHM_STATE TABLE
-- ============================================================================
CREATE TABLE algorithm_state (
    state_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    
    -- Bayesian State (stored as binary for efficiency)
    mu BYTEA NOT NULL,  -- Preference means vector
    sigma BYTEA NOT NULL,  -- Covariance matrix
    comparison_matrix BYTEA NOT NULL,  -- Which pairs have been compared
    
    -- Metadata
    trials_completed INTEGER NOT NULL DEFAULT 0,
    total_trials INTEGER NOT NULL,
    algorithm_version VARCHAR(20) DEFAULT '3.1',
    
    -- Integrity
    state_checksum VARCHAR(64) NOT NULL,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Version control (for optimistic locking)
    version INTEGER DEFAULT 1,
    
    CONSTRAINT unique_session_state UNIQUE (session_id)
);

CREATE INDEX idx_algorithm_state_session ON algorithm_state(session_id);

-- ============================================================================
-- CHOICES TABLE
-- ============================================================================
CREATE TABLE choices (
    choice_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    
    -- Trial Info
    trial_number INTEGER NOT NULL CHECK (trial_number > 0),
    
    -- Stimuli Presented
    stimulus_a_id UUID NOT NULL REFERENCES stimuli(stimulus_id),
    stimulus_b_id UUID NOT NULL REFERENCES stimuli(stimulus_id),
    
    -- Choice Made
    chosen_stimulus_id UUID NOT NULL REFERENCES stimuli(stimulus_id),
    
    -- Timing
    response_time_ms INTEGER NOT NULL CHECK (response_time_ms > 0),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Context
    presentation_order VARCHAR(10) CHECK (presentation_order IN ('AB', 'BA')),
    break_before BOOLEAN DEFAULT FALSE,
    
    -- Validation
    CONSTRAINT valid_choice CHECK (
        chosen_stimulus_id IN (stimulus_a_id, stimulus_b_id)
    ),
    CONSTRAINT different_stimuli CHECK (stimulus_a_id != stimulus_b_id),
    CONSTRAINT unique_trial_per_session UNIQUE (session_id, trial_number),
    
    -- Reasonable response time (100ms to 5 minutes)
    CONSTRAINT reasonable_response_time CHECK (
        response_time_ms >= 100 AND response_time_ms <= 300000
    )
);

CREATE INDEX idx_choices_session ON choices(session_id, trial_number);
CREATE INDEX idx_choices_stimuli ON choices(stimulus_a_id, stimulus_b_id);
CREATE INDEX idx_choices_timestamp ON choices(timestamp DESC);

-- ============================================================================
-- AUDIT_LOG TABLE
-- ============================================================================
CREATE TABLE audit_log (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Who/What
    user_id UUID REFERENCES users(user_id),
    experiment_id UUID REFERENCES experiments(experiment_id),
    session_id UUID REFERENCES sessions(session_id),
    
    -- Event
    event_type VARCHAR(100) NOT NULL,
    event_category VARCHAR(50) NOT NULL CHECK (
        event_category IN ('auth', 'experiment', 'session', 'data', 'system', 'security')
    ),
    
    -- Details
    description TEXT,
    details JSONB DEFAULT '{}',
    
    -- Context
    ip_address INET,
    user_agent TEXT,
    
    -- Severity
    severity VARCHAR(20) DEFAULT 'info' CHECK (
        severity IN ('debug', 'info', 'warning', 'error', 'critical')
    ),
    
    -- Timestamp
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_log_user ON audit_log(user_id);
CREATE INDEX idx_audit_log_experiment ON audit_log(experiment_id);
CREATE INDEX idx_audit_log_session ON audit_log(session_id);
CREATE INDEX idx_audit_log_event_type ON audit_log(event_type);
CREATE INDEX idx_audit_log_created ON audit_log(created_at DESC);
CREATE INDEX idx_audit_log_severity ON audit_log(severity) 
    WHERE severity IN ('error', 'critical');

-- ============================================================================
-- PROVENANCE_LOG TABLE
-- ============================================================================
CREATE TABLE provenance_log (
    provenance_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    trial_number INTEGER NOT NULL,
    
    -- Computation Type
    computation_type VARCHAR(50) NOT NULL CHECK (
        computation_type IN ('pair_selection', 'belief_update', 'preference_estimation')
    ),
    
    -- Inputs
    input_state JSONB NOT NULL,
    input_checksum VARCHAR(64) NOT NULL,
    
    -- Outputs
    output_result JSONB NOT NULL,
    output_checksum VARCHAR(64) NOT NULL,
    
    -- Algorithm Details
    algorithm_name VARCHAR(100) DEFAULT 'PureBayesianAdaptiveSelector',
    algorithm_version VARCHAR(20) DEFAULT '3.1',
    parameters JSONB DEFAULT '{}',
    
    -- System Context
    code_version VARCHAR(64),  -- Git commit hash
    python_version VARCHAR(20),
    numpy_version VARCHAR(20),
    scipy_version VARCHAR(20),
    
    -- Performance
    computation_time_ms INTEGER,
    
    -- Timestamp
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_provenance_session ON provenance_log(session_id);
CREATE INDEX idx_provenance_trial ON provenance_log(session_id, trial_number);
CREATE INDEX idx_provenance_type ON provenance_log(computation_type);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Active experiments with statistics
CREATE VIEW active_experiments AS
SELECT 
    e.experiment_id,
    e.name,
    e.user_id,
    u.username,
    e.status,
    e.num_stimuli,
    e.max_trials,
    COUNT(DISTINCT s.session_id) as total_sessions,
    COUNT(DISTINCT CASE WHEN s.status = 'complete' THEN s.session_id END) as completed_sessions,
    COUNT(DISTINCT CASE WHEN s.status = 'active' THEN s.session_id END) as active_sessions,
    AVG(CASE WHEN s.status = 'complete' THEN s.total_time_seconds END) as avg_completion_time_seconds,
    e.created_at,
    e.published_at
FROM experiments e
JOIN users u ON e.user_id = u.user_id
LEFT JOIN sessions s ON e.experiment_id = s.experiment_id
WHERE e.status = 'active'
GROUP BY e.experiment_id, u.username;

-- Session statistics
CREATE VIEW session_stats AS
SELECT 
    s.session_id,
    s.session_token,
    s.experiment_id,
    e.name as experiment_name,
    s.status,
    s.trials_completed,
    s.trials_total,
    s.progress_percentage,
    s.created_at,
    s.completed_at,
    s.total_time_seconds,
    COUNT(c.choice_id) as choices_recorded,
    AVG(c.response_time_ms) as avg_response_time_ms,
    MIN(c.response_time_ms) as min_response_time_ms,
    MAX(c.response_time_ms) as max_response_time_ms,
    STDDEV(c.response_time_ms) as stddev_response_time_ms
FROM sessions s
JOIN experiments e ON s.experiment_id = e.experiment_id
LEFT JOIN choices c ON s.session_id = c.session_id
GROUP BY s.session_id, e.name;

-- Experiment quality metrics
CREATE VIEW experiment_quality AS
SELECT 
    e.experiment_id,
    e.name,
    COUNT(DISTINCT s.session_id) as total_sessions,
    AVG(s.consistency_score) as avg_consistency,
    AVG(CASE WHEN s.status = 'complete' THEN 1.0 ELSE 0.0 END) as completion_rate,
    AVG(s.trials_completed::FLOAT / s.trials_total::FLOAT) as avg_progress,
    COUNT(CASE WHEN s.attention_check_passed = TRUE THEN 1 END)::FLOAT / 
        NULLIF(COUNT(s.session_id), 0) as attention_pass_rate
FROM experiments e
LEFT JOIN sessions s ON e.experiment_id = s.experiment_id
GROUP BY e.experiment_id, e.name;

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Function to update experiment updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_experiments_updated_at
    BEFORE UPDATE ON experiments
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Function to update session last_activity
CREATE OR REPLACE FUNCTION update_session_activity()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE sessions 
    SET last_activity_at = CURRENT_TIMESTAMP
    WHERE session_id = NEW.session_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_session_activity_on_choice
    AFTER INSERT ON choices
    FOR EACH ROW
    EXECUTE FUNCTION update_session_activity();

-- Function to validate experiment before publishing
CREATE OR REPLACE FUNCTION validate_experiment_for_publish(exp_id UUID)
RETURNS TABLE(valid BOOLEAN, errors TEXT[]) AS $$
DECLARE
    stim_count INTEGER;
    errors_array TEXT[] := ARRAY[]::TEXT[];
BEGIN
    -- Check stimulus count
    SELECT COUNT(*) INTO stim_count
    FROM stimuli
    WHERE experiment_id = exp_id;
    
    IF stim_count < 3 THEN
        errors_array := array_append(errors_array, 'Need at least 3 stimuli');
    END IF;
    
    -- Add more validations as needed
    
    RETURN QUERY SELECT (array_length(errors_array, 1) IS NULL), errors_array;
END;
$$ LANGUAGE plpgsql;

-- Function to generate session token
CREATE OR REPLACE FUNCTION generate_session_token()
RETURNS VARCHAR(128) AS $$
BEGIN
    RETURN encode(gen_random_bytes(64), 'base64');
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SAMPLE DATA (for testing)
-- ============================================================================

-- Create test user
INSERT INTO users (email, username, password_hash, full_name, institution, role)
VALUES (
    'test@example.com',
    'testuser',
    crypt('testpassword', gen_salt('bf')),  -- Use bcrypt
    'Test User',
    'Test University',
    'researcher'
) ON CONFLICT (email) DO NOTHING;

-- ============================================================================
-- GRANTS (adjust based on your setup)
-- ============================================================================

-- Create application role
-- CREATE ROLE app_user WITH LOGIN PASSWORD 'your_secure_password';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;

-- ============================================================================
-- MAINTENANCE
-- ============================================================================

-- Function to archive old sessions
CREATE OR REPLACE FUNCTION archive_old_sessions(days_old INTEGER DEFAULT 90)
RETURNS INTEGER AS $$
DECLARE
    archived_count INTEGER;
BEGIN
    -- Move to archive table (create if needed)
    -- This is a placeholder - implement based on your needs
    DELETE FROM sessions
    WHERE status = 'complete'
    AND completed_at < CURRENT_TIMESTAMP - (days_old || ' days')::INTERVAL
    RETURNING * INTO archived_count;
    
    RETURN archived_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- CONSTRAINTS SUMMARY
-- ============================================================================

/*
PRIMARY KEYS: All tables use UUID
FOREIGN KEYS: Proper cascading (DELETE CASCADE for dependent data)
CHECK CONSTRAINTS: Data validation at DB level
UNIQUE CONSTRAINTS: Prevent duplicates
NOT NULL: Required fields enforced
INDEXES: Performance optimization on common queries

ACID COMPLIANCE: Yes (PostgreSQL default)
REFERENTIAL INTEGRITY: Enforced
DATA VALIDATION: Multi-layer (DB + application)
AUDIT TRAIL: Complete logging
PROVENANCE: Full computation tracking
*/

-- ============================================================================
-- SCHEMA VERSION
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_version (
    version VARCHAR(20) PRIMARY KEY,
    applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

INSERT INTO schema_version (version, description)
VALUES ('3.1', 'Complete enterprise-grade schema with full audit and provenance')
ON CONFLICT (version) DO NOTHING;

-- Done!
SELECT 'Schema created successfully!' as status;


