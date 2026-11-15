from .embedder import embed_query
from .db import run_rpc


def retrieve_top_chunks(query: str, top_k: int = 5):
    """Retrieve the top-K relevant text chunks using vector similarity search."""
    query_emb = embed_query(query)
    results = run_rpc(query_emb, top_k)

    if not results:
        return []

    cleaned = []
    for row in results:
        content = row.get("chunk_text")
        metadata = row.get("metadata") or {}
        distance = row.get("distance")

        cleaned.append({
            "content": content,
            "metadata": metadata,

            "similarity": distance,
        })

    return cleaned
