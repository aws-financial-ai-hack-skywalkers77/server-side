-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm; -- For text search

-- ============================================================================
-- CORE KNOWLEDGE BASE TABLES
-- ============================================================================

-- Tax law documents (chunked and vectorized)
CREATE TABLE tax_laws (
    id SERIAL PRIMARY KEY,
    jurisdiction VARCHAR(100) NOT NULL,        -- 'US-NY', 'EU-DE', 'EU-FR', 'UK', 'CA-ON'
    jurisdiction_type VARCHAR(50),             -- 'federal', 'state', 'country', 'province'
    law_category VARCHAR(100) NOT NULL,        -- 'income_tax', 'corporate_tax', 'vat', 'capital_gains'
    document_title TEXT NOT NULL,
    document_source TEXT,                      -- Official source URL/reference
    effective_date DATE,                       -- When this law became effective
    expiry_date DATE,                          -- NULL if still active
    chunk_text TEXT NOT NULL,
    chunk_index INTEGER,
    section_reference VARCHAR(255),            -- e.g., 'Section 179', '§26 EStG'
    metadata JSONB,
    embedding vector(384),  -- Changed to 384 for local model (all-MiniLM-L6-v2). Use 768 for OpenAI/Gemini.
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_tax_laws_embedding ON tax_laws USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_tax_laws_jurisdiction ON tax_laws (jurisdiction);
CREATE INDEX idx_tax_laws_category ON tax_laws (law_category);
CREATE INDEX idx_tax_laws_effective_date ON tax_laws (effective_date);

-- Form templates and requirements
CREATE TABLE form_templates (
    id SERIAL PRIMARY KEY,
    jurisdiction VARCHAR(100) NOT NULL,
    form_code VARCHAR(100) NOT NULL,           -- 'Form 1040', 'Schedule C', 'Anlage N'
    form_name TEXT NOT NULL,
    tax_year INTEGER NOT NULL,
    taxpayer_type VARCHAR(100),                -- 'individual', 'corporate', 'partnership'
    description TEXT,
    filing_deadline VARCHAR(100),              -- 'April 15', '3 months after year end'
    form_url TEXT,                             -- Link to official form
    required_fields JSONB,                     -- Array of required field definitions
    calculation_rules JSONB,                   -- Validation and calculation formulas
    dependencies JSONB,                        -- What other forms/schedules are needed
    embedding vector(384),  -- Changed to 384 for local model (all-MiniLM-L6-v2). Use 768 for OpenAI/Gemini.
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_form_templates_jurisdiction ON form_templates (jurisdiction);
CREATE INDEX idx_form_templates_code ON form_templates (form_code);
CREATE INDEX idx_form_templates_year ON form_templates (tax_year);

-- Tax treaties and bilateral agreements
CREATE TABLE tax_treaties (
    id SERIAL PRIMARY KEY,
    country_a VARCHAR(100) NOT NULL,
    country_b VARCHAR(100) NOT NULL,
    treaty_name TEXT NOT NULL,
    signed_date DATE,
    effective_date DATE,
    treaty_type VARCHAR(100),                  -- 'double_taxation', 'information_exchange'
    treaty_text TEXT,
    key_provisions JSONB,                      -- Structured data about rates, exemptions
    article_chunks JSONB,                      -- Array of treaty articles with embeddings
    embedding vector(384),  -- Changed to 384 for local model (all-MiniLM-L6-v2). Use 768 for OpenAI/Gemini.
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_treaties_countries ON tax_treaties (country_a, country_b);

-- Tax rates and calculation rules
CREATE TABLE tax_rates (
    id SERIAL PRIMARY KEY,
    jurisdiction VARCHAR(100) NOT NULL,
    rate_type VARCHAR(100) NOT NULL,           -- 'income_bracket', 'capital_gains', 'vat', 'corporate'
    tax_year INTEGER NOT NULL,
    taxpayer_type VARCHAR(100),
    rate_structure JSONB NOT NULL,             -- Progressive brackets, flat rates, etc.
    special_conditions JSONB,                  -- Thresholds, phase-outs, etc.
    source_reference TEXT,
    effective_date DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_tax_rates_jurisdiction ON tax_rates (jurisdiction);
CREATE INDEX idx_tax_rates_year ON tax_rates (tax_year);

-- ============================================================================
-- WORKFLOW 1: FORM COMPLETENESS CHECKER
-- ============================================================================

-- Uploaded tax documents for checking
CREATE TABLE tax_documents (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(100) UNIQUE NOT NULL,
    jurisdiction VARCHAR(100) NOT NULL,
    form_code VARCHAR(100),
    tax_year INTEGER,
    client_name VARCHAR(255),
    client_type VARCHAR(100),                  -- 'individual', 'corporate'
    uploaded_by VARCHAR(255),
    raw_file_path TEXT,
    extracted_data JSONB,                      -- Parsed form data from Landing AI
    document_type VARCHAR(100),                -- 'draft', 'filed', 'amended'
    status VARCHAR(50) DEFAULT 'uploaded',     -- 'uploaded', 'processing', 'checked', 'filed'
    embedding vector(384),  -- Changed to 384 for local model (all-MiniLM-L6-v2). Use 768 for OpenAI/Gemini.
    uploaded_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

CREATE INDEX idx_tax_documents_id ON tax_documents (document_id);
CREATE INDEX idx_tax_documents_jurisdiction ON tax_documents (jurisdiction);

-- Completeness check results
CREATE TABLE completeness_checks (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(100) REFERENCES tax_documents(document_id),
    check_type VARCHAR(100),                   -- 'required_fields', 'calculations', 'cross_reference'
    status VARCHAR(50),                        -- 'pass', 'fail', 'warning'
    severity VARCHAR(50),                      -- 'critical', 'high', 'medium', 'low'
    field_name VARCHAR(255),
    issue_description TEXT,
    expected_value TEXT,
    actual_value TEXT,
    form_reference TEXT,                       -- Which form/schedule
    resolution_suggestion TEXT,
    is_resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_completeness_document ON completeness_checks (document_id);
CREATE INDEX idx_completeness_status ON completeness_checks (status);

-- ============================================================================
-- WORKFLOW 2: JURISDICTION COMPARISON
-- ============================================================================

-- Comparison requests
CREATE TABLE jurisdiction_comparisons (
    id SERIAL PRIMARY KEY,
    comparison_id VARCHAR(100) UNIQUE NOT NULL,
    base_jurisdiction VARCHAR(100) NOT NULL,   -- What they know (e.g., 'US-NY')
    target_jurisdiction VARCHAR(100) NOT NULL, -- What they're learning (e.g., 'EU-DE')
    comparison_scope VARCHAR(100),             -- 'individual_income', 'corporate', 'vat'
    tax_year INTEGER,
    requested_by VARCHAR(255),
    comparison_results JSONB,                  -- Structured comparison data
    created_at TIMESTAMP DEFAULT NOW()
);

-- Jurisdiction difference highlights
CREATE TABLE jurisdiction_differences (
    id SERIAL PRIMARY KEY,
    comparison_id VARCHAR(100) REFERENCES jurisdiction_comparisons(comparison_id),
    difference_type VARCHAR(100),              -- 'filing_deadline', 'deduction', 'rate', 'form_requirement'
    category VARCHAR(100),
    base_rule TEXT,
    target_rule TEXT,
    base_law_id INTEGER REFERENCES tax_laws(id),
    target_law_id INTEGER REFERENCES tax_laws(id),
    impact_level VARCHAR(50),                  -- 'critical', 'important', 'informational'
    explanation TEXT,
    examples JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_differences_comparison ON jurisdiction_differences (comparison_id);

-- ============================================================================
-- WORKFLOW 3: MULTI-JURISDICTION TAX PLANNING
-- ============================================================================

-- Client profiles for planning
CREATE TABLE client_profiles (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(100) UNIQUE NOT NULL,
    client_name VARCHAR(255) NOT NULL,
    client_type VARCHAR(100),                  -- 'individual', 'corporate', 'trust'
    primary_jurisdiction VARCHAR(100),
    income_sources JSONB,                      -- Array of {jurisdiction, type, amount_range}
    business_activities JSONB,
    assets JSONB,
    special_circumstances JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Planning scenarios
CREATE TABLE planning_scenarios (
    id SERIAL PRIMARY KEY,
    scenario_id VARCHAR(100) UNIQUE NOT NULL,
    client_id VARCHAR(100) REFERENCES client_profiles(client_id),
    scenario_name VARCHAR(255),
    jurisdictions_involved VARCHAR(100)[],
    tax_year INTEGER,
    scenario_description TEXT,
    objectives JSONB,                          -- What client wants to optimize
    constraints JSONB,                         -- Legal/regulatory constraints
    analysis_results JSONB,                    -- Planning recommendations
    created_at TIMESTAMP DEFAULT NOW()
);

-- Tax exposure analysis
CREATE TABLE tax_exposures (
    id SERIAL PRIMARY KEY,
    scenario_id VARCHAR(100) REFERENCES planning_scenarios(scenario_id),
    jurisdiction VARCHAR(100),
    exposure_type VARCHAR(100),                -- 'double_taxation', 'withholding', 'reporting_requirement'
    risk_level VARCHAR(50),                    -- 'high', 'medium', 'low'
    estimated_impact_min DECIMAL(15,2),
    estimated_impact_max DECIMAL(15,2),
    applicable_treaty_id INTEGER REFERENCES tax_treaties(id),
    mitigation_strategies JSONB,
    law_references JSONB,                      -- Array of law IDs
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_exposures_scenario ON tax_exposures (scenario_id);
CREATE INDEX idx_exposures_risk ON tax_exposures (risk_level);

-- Planning recommendations
CREATE TABLE planning_recommendations (
    id SERIAL PRIMARY KEY,
    scenario_id VARCHAR(100) REFERENCES planning_scenarios(scenario_id),
    recommendation_type VARCHAR(100),          -- 'structure', 'timing', 'documentation', 'treaty_benefit'
    priority VARCHAR(50),                      -- 'critical', 'high', 'medium', 'low'
    title TEXT NOT NULL,
    description TEXT,
    expected_benefit TEXT,
    implementation_steps JSONB,
    risks_and_considerations JSONB,
    supporting_law_ids INTEGER[],
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- AUDIT & TRACKING
-- ============================================================================

-- Search and query logs
CREATE TABLE query_logs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(100),
    workflow VARCHAR(50),                      -- 'completeness', 'comparison', 'planning'
    query_text TEXT,
    query_embedding vector(384),  -- Changed to 384 for local model
    jurisdictions VARCHAR(100)[],
    results_count INTEGER,
    response_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_query_logs_workflow ON query_logs (workflow);
CREATE INDEX idx_query_logs_created ON query_logs (created_at);

-- User activity tracking
CREATE TABLE user_activities (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(100),
    activity_type VARCHAR(100),
    workflow VARCHAR(50),
    document_id VARCHAR(100),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- HELPER VIEWS
-- ============================================================================

-- Active tax laws (not expired)
CREATE VIEW active_tax_laws AS
SELECT * FROM tax_laws
WHERE expiry_date IS NULL OR expiry_date > CURRENT_DATE;

-- Current year tax rates
CREATE VIEW current_tax_rates AS
SELECT * FROM tax_rates
WHERE tax_year = EXTRACT(YEAR FROM CURRENT_DATE);

-- Critical completeness issues
CREATE VIEW critical_issues AS
SELECT 
    cc.*,
    td.client_name,
    td.jurisdiction,
    td.form_code
FROM completeness_checks cc
JOIN tax_documents td ON cc.document_id = td.document_id
WHERE cc.severity = 'critical' AND cc.is_resolved = FALSE;

-- ============================================================================
-- SAMPLE DATA HELPER FUNCTIONS
-- ============================================================================

-- Function to search laws by semantic similarity
CREATE OR REPLACE FUNCTION search_laws_by_similarity(
    query_embedding vector(384),  -- Changed to 384 for local model
    target_jurisdiction VARCHAR(100),
    result_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    law_id INTEGER,
    similarity FLOAT,
    chunk_text TEXT,
    section_reference VARCHAR(255),
    document_title TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        tl.id,
        1 - (tl.embedding <=> query_embedding) as similarity,
        tl.chunk_text,
        tl.section_reference,
        tl.document_title
    FROM tax_laws tl
    WHERE tl.jurisdiction = target_jurisdiction
    ORDER BY tl.embedding <=> query_embedding
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql;