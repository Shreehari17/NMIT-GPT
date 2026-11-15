from supabase import create_client
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
def get_supabase_client():
    return supabase


def run_rpc(embedding: list, top_k: int):

    """Execute vector similarity search via Supabase RPC."""
    response = supabase.rpc(
    "match_documents",
    {
        "filter_source":None,
        "match_count": top_k,
        "query_embedding": embedding
    }
    ).execute()
    return response.data
