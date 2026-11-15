from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from RAG_ENGINE.src.db import get_supabase_client
from backend.auth_utils import require_admin

router = APIRouter(prefix="/debug", tags=["Debug"])
supabase = get_supabase_client()

class RPCRequest(BaseModel):
    embedding: List[float]
    match_count: int = 5

# Exposes raw vector-DB search with no filtering - was previously reachable
# by anyone, logged in or not. Restricted to admins only.
@router.post("/rpc/match", dependencies=[require_admin()])
def debug_rpc(req: RPCRequest):
    response = supabase.rpc(
        "match_documents",
        {
            "query_embedding": req.embedding,
            "match_count": req.match_count
        }
    ).execute()

    return response.data
