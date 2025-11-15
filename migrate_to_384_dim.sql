-- Migration script to change embedding dimensions from 768 to 384
-- This is needed for the free local embedding model (all-MiniLM-L6-v2)
-- Run this if you're switching to the local model

-- Note: This will require dropping and recreating tables with embeddings
-- If you have existing data, you'll need to re-ingest it

-- Drop existing indexes
DROP INDEX IF EXISTS idx_tax_laws_embedding;
DROP INDEX IF EXISTS idx_form_templates_embedding;
DROP INDEX IF EXISTS idx_tax_treaties_embedding;

-- Alter tables to change vector dimension
-- Note: pgvector doesn't support ALTER COLUMN for vector dimensions
-- So we need to recreate the columns

-- For tax_laws table
ALTER TABLE tax_laws DROP COLUMN IF EXISTS embedding;
ALTER TABLE tax_laws ADD COLUMN embedding vector(384);

-- For form_templates table  
ALTER TABLE form_templates DROP COLUMN IF EXISTS embedding;
ALTER TABLE form_templates ADD COLUMN embedding vector(384);

-- For tax_treaties table
ALTER TABLE tax_treaties DROP COLUMN IF EXISTS embedding;
ALTER TABLE tax_treaties ADD COLUMN embedding vector(384);

-- For tax_documents table (if it exists)
ALTER TABLE tax_documents DROP COLUMN IF EXISTS embedding;
ALTER TABLE tax_documents ADD COLUMN embedding vector(384);

-- Recreate indexes
CREATE INDEX idx_tax_laws_embedding ON tax_laws USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_form_templates_embedding ON form_templates USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_tax_treaties_embedding ON tax_treaties USING ivfflat (embedding vector_cosine_ops);

-- Update function signatures
DROP FUNCTION IF EXISTS search_laws_by_similarity(vector, VARCHAR, INTEGER);
CREATE OR REPLACE FUNCTION search_laws_by_similarity(
    query_embedding vector(384),
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

