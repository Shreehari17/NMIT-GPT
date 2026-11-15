CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE unified_embeddings (
    embedding_id SERIAL PRIMARY KEY,

    source_type TEXT NOT NULL,
    source_id VARCHAR(50) NOT NULL,

    chunk_type TEXT,
    chunk_index INTEGER,
    raw_text TEXT NOT NULL,
    metadata JSONB,

    embedding VECTOR(768) NOT NULL,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT valid_chunk_logic CHECK (
        (chunk_type IS NULL AND chunk_index IS NULL)
        OR
        (chunk_type IS NOT NULL AND chunk_index IS NOT NULL)
    )
);
