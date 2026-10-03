-- Run once in the Supabase SQL editor. No new table: it only searches the
-- existing unified_embeddings table, restricted to source_type = 'circular'.
CREATE OR REPLACE FUNCTION match_circulars (
    query_embedding vector(768),
    match_count     int DEFAULT 12
)
RETURNS TABLE (
    source_id   text,
    chunk_type  text,
    chunk_index int,
    chunk_text  text,
    similarity  float,
    metadata    jsonb
)
LANGUAGE sql STABLE
AS $$
    SELECT
        ue.source_id::text,
        ue.chunk_type,
        ue.chunk_index,
        ue.raw_text,
        (1 - (ue.embedding <=> query_embedding))::float,
        ue.metadata
    FROM unified_embeddings ue
    WHERE ue.source_type = 'circular'
    ORDER BY ue.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- optional: faster lookups when reassembling / deleting a circular's chunks
CREATE INDEX IF NOT EXISTS idx_unified_embeddings_source
    ON unified_embeddings (source_type, source_id);