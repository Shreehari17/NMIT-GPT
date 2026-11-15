from fastapi import APIRouter
from RAG_ENGINE.src.db import get_supabase_client

router = APIRouter(prefix="/health", tags=["Health"])
supabase = get_supabase_client()

@router.get("/")
def health_check():
    try:
        supabase.table("faculty_biodata").select("faculty_id").limit(1).execute()
        return {"status": "ok"}
    except:
        return {"status": "error"}
