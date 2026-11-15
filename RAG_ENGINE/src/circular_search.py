"""
Answer questions from circulars stored in unified_embeddings (source_type='circular').

1. Embed the question, vector-search circular chunks (RPC match_circulars).
2. Pick the best 1-2 circulars, then reload ALL their chunks in order, so the LLM sees the
   whole circular (e.g. General + Girls + Boys sections), not just the closest fragment.
3. Ask the LLM to answer strictly from that text.
"""
import os
from datetime import datetime

from .db import get_supabase_client
from .embedder import embed_query
from .llm_interface import client as answer_client, MODEL

MIN_SIM_FORCED = float(os.getenv("CIRCULAR_MIN_SIMILARITY", "0.25"))          # parser said "circular"
MIN_SIM_GENERAL = float(os.getenv("CIRCULAR_GENERAL_MIN_SIMILARITY", "0.40"))  # parser said "general"
CHUNK_CANDIDATES = 12
MAX_CIRCULARS = 2
SECOND_CIRCULAR_MARGIN = 0.08
MAX_CHARS_PER_CIRCULAR = 6000
NOT_FOUND = "NOT_IN_CIRCULARS"


def _search_text(query: str, chat_history: list) -> str:
    """Short follow-ups ("what about boys?") borrow the previous user question for retrieval."""
    if chat_history and len(query.split()) <= 6:
        for m in reversed(chat_history):
            if m.get("role") == "user" and m.get("content") != query:
                return f"{m['content'][:200]} {query}"
    return query


def _readable(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %B %Y").lstrip("0")
    except (TypeError, ValueError):
        return ""


def find_circulars(query: str, chat_history: list = None, min_sim: float = MIN_SIM_FORCED) -> list:
    supabase = get_supabase_client()
    emb = embed_query(_search_text(query, chat_history or []))
    hits = supabase.rpc("match_circulars", {"query_embedding": emb, "match_count": CHUNK_CANDIDATES}).execute().data or []
    if not hits:
        return []

    best = {}
    for h in hits:
        best[h["source_id"]] = max(best.get(h["source_id"], 0.0), h.get("similarity") or 0.0)
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    print("CIRCULAR SIMILARITY:", ranked[:3])

    top_sim = ranked[0][1]
    if top_sim < min_sim:
        return []
    ranked = [(cid, s) for cid, s in ranked if s >= top_sim - SECOND_CIRCULAR_MARGIN][:MAX_CIRCULARS]

    ids = [cid for cid, _ in ranked]
    rows = (
        supabase.table("unified_embeddings")
        .select("source_id, chunk_type, chunk_index, raw_text, metadata")
        .eq("source_type", "circular")
        .in_("source_id", ids)
        .order("chunk_index")
        .execute()
        .data
    )

    docs = []
    for cid, sim in ranked:
        chunks = sorted([r for r in rows if r["source_id"] == cid], key=lambda r: r["chunk_index"])
        if not chunks:
            continue
        meta = chunks[0].get("metadata") or {}
        sections = []
        for r in chunks:
            if str(r["chunk_type"]).startswith("00_"):
                continue                                    # summary chunk, body is in the sections
            text = r["raw_text"]
            body = text.split("\n", 1)[1] if "\n" in text else text   # drop the repeated header line
            sections.append(f"[{(r.get('metadata') or {}).get('section', 'Section')}]\n{body}")
        docs.append({"circular_id": cid, "similarity": sim, "meta": meta, "body": "\n\n".join(sections)})
    return docs


def _build_context(docs: list) -> str:
    parts = []
    for i, d in enumerate(docs, 1):
        m = d["meta"]
        body = d["body"][:MAX_CHARS_PER_CIRCULAR]
        parts.append(
            f"=== CIRCULAR {i} ===\n"
            f"Title: {m.get('title', '')}\n"
            f"Number: {m.get('circular_no') or 'n/a'}\n"
            f"Date: {_readable(m.get('circular_date')) or 'n/a'}\n"
            f"Issued by: {m.get('issued_by') or 'n/a'}\n"
            f"Applies to: {m.get('applies_to') or 'n/a'}\n"
            f"Text:\n{body}"
        )
    return "\n\n".join(parts)


SYSTEM_PROMPT = """You are NMIT-GPT, the assistant of Nitte Meenakshi Institute of Technology (NMIT).
Answer the student's question using ONLY the circulars provided. Today's date is {today}.

Rules:
- Use only what the circular text says. Never add rules, exceptions or advice that are not written there.
- Keep every number, length, time, date and amount exactly as written.
- If the question is about one group (girls, boys, faculty, hostellers...), give that group's rules AND any
  rules that apply to everyone (e.g. a "General Guidelines" section). Do not mix in the other group's rules.
- If the question is broad ("what is the dress code"), cover every group in the circular.
- If two circulars conflict, follow the one with the later date and say which one.
- Be concise: a short list for rules, one sentence for a simple fact.
- Finish with one line: "Source: <title>, Circular No. <number>, dated <date>" (skip parts that are n/a).
- If the circulars do not contain the answer, reply with exactly: NOT_IN_CIRCULARS"""


def answer_from_circulars(query: str, chat_history: list = None, force: bool = False):
    """Returns the answer dict, or None when the question is not about a circular
    (so the caller can fall back to the normal pipeline). force=True means the parser
    already decided it's a circular question, so a 'not found' message is returned instead of None."""
    chat_history = chat_history or []
    docs = find_circulars(query, chat_history, MIN_SIM_FORCED if force else MIN_SIM_GENERAL)
    not_found = {
        "query": query,
        "answer": "I couldn't find anything about that in the circulars uploaded so far.",
        "chunks_used": [],
    }
    if not docs:
        return not_found if force else None

    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(today=datetime.now().strftime("%A, %d %B %Y"))}]
    messages += [{"role": m["role"], "content": m["content"][:500]} for m in chat_history[-4:]]
    messages.append({"role": "user", "content": f"[Circulars]\n{_build_context(docs)}\n\n[Question]\n{query}"})

    resp = answer_client.chat.completions.create(model=MODEL, max_tokens=900, temperature=0, messages=messages)
    answer = (resp.choices[0].message.content or "").strip()

    if NOT_FOUND in answer:
        return not_found if force else None

    return {
        "query": query,
        "answer": answer,
        "chunks_used": [
            {"content": d["body"], "metadata": d["meta"], "similarity": d["similarity"]} for d in docs
        ],
    }