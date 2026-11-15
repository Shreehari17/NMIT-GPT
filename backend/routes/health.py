from fastapi import APIRouter, HTTPException
from RAG_ENGINE.src.db import get_supabase_client

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/")
def health_check():
    try:
        supabase = get_supabase_client()
        supabase.table("faculty_biodata").select("faculty_id").limit(1).execute()
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database health check failed"
        )
