create function match_documents (
    query_embedding vector(768),
    match_count int default 5,
    filter_source text default null
)
returns table (
    source_id text,
    source_type text,
    chunk_type text,
    chunk_index int,
    chunk_text text,
    similarity float,
    metadata jsonb
)
language sql
as $$
    select
        source_id,
        chunk_type,
        chunk_index,
        raw_text as chunk_text,
        1 - (embedding <=> query_embedding) as similarity,
        metadata
    from unified_embeddings
    where (filter_source is null or source_type = filter_source)
    order by embedding <=> query_embedding
    limit match_count;
$$;
