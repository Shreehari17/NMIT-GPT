
RAG_ENGINE

This directory contains the runtime Retrieval-Augmented Generation engine for Faculty-GPT.

Modules:
1. embedder.py       - Generates MPNet-base-v2 embeddings for queries
2. db.py             - Supabase connection + RPC execution
3. retriever.py      - Vector similarity search (top-K chunks)
4. llm_interface.py  - LLaMA-3 inference using Groq API
5. pipeline.py       - Orchestrates the RAG flow and returns final JSON

Required environment variables in .env:
SUPABASE_URL
SUPABASE_KEY
GROQ_API_KEY
EMBEDDING_MODEL

API Integration:
Call the following function from your backend API:

from RAG_ENGINE.src.pipeline import answer_query

result = answer_query(question_string)

This returns:
- final answer
- retrieved chunks
- metadata
