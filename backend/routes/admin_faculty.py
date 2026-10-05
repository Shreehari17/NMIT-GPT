"""
Admin: Faculty management (list / add / update / delete).

Table: faculty_biodata (see data_pipeline/supabase/faculty_biodata_table.sql)

Notes
- faculty_id is generated server-side as FAC<n>, same convention as
  data_pipeline/main.py.
- The chatbot answers faculty questions from `unified_embeddings`
  (source_type='faculty_biodata'). So after add/update we refresh that
  faculty's embedding chunks, and on delete we remove them, otherwise the
  chatbot would keep answering with stale / deleted data.
- Deleting a faculty also deletes their rows in `subjects`
  (ON DELETE CASCADE in subjects.sql).
- RAG_ENGINE code is only imported (to reuse the already-loaded embedding
  model); nothing in it is modified.
"""
import re
import traceback
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from backend.auth_utils import require_admin
from RAG_ENGINE.src.db import get_supabase_client

router = APIRouter(prefix="/admin/faculty", tags=["Admin - Faculty"])
supabase = get_supabase_client()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Columns that hold TEXT[] in Postgres
ARRAY_FIELDS = [
    "email",
    "educational_qualifications",
    "past_experience",
    "areas_of_interest",
    "achievements",
    "subjects_taught",
    "scholar_id",
    "orcid_id",
    "linkedin_id",
]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class FacultyPayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    designation: Optional[str] = ""
    department: Optional[str] = ""
    faculty_shortform: Optional[str] = ""
    joining_date: Optional[str] = ""  # YYYY-MM-DD or empty
    research: Optional[str] = ""

    email: List[str] = Field(default_factory=list)
    educational_qualifications: List[str] = Field(default_factory=list)
    past_experience: List[str] = Field(default_factory=list)
    areas_of_interest: List[str] = Field(default_factory=list)
    achievements: List[str] = Field(default_factory=list)
    subjects_taught: List[str] = Field(default_factory=list)
    scholar_id: List[str] = Field(default_factory=list)
    orcid_id: List[str] = Field(default_factory=list)
    linkedin_id: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_list(values: List[str]) -> List[str]:
    return [v.strip() for v in (values or []) if v and v.strip()]


def _to_row(p: FacultyPayload) -> dict:
    if p.joining_date and not _DATE_RE.match(p.joining_date):
        raise HTTPException(status_code=400, detail="Joining date must be YYYY-MM-DD.")

    row = {
        "name": p.name.strip(),
        "designation": (p.designation or "").strip() or None,
        "department": (p.department or "").strip() or None,
        "joining_date": p.joining_date or None,
        "research": (p.research or "").strip() or None,
    }
    shortform = (p.faculty_shortform or "").strip().upper()
    row["faculty_shortform"] = shortform or None
    for f in ARRAY_FIELDS:
        row[f] = _clean_list(getattr(p, f))
    return row


def _next_faculty_id() -> str:
    data = supabase.table("faculty_biodata").select("faculty_id").execute().data or []
    nums = [
        int(r["faculty_id"][3:])
        for r in data
        if r["faculty_id"].startswith("FAC") and r["faculty_id"][3:].isdigit()
    ]
    return f"FAC{(max(nums) + 1) if nums else 1}"


def _build_chunks(row: dict):
    """Same chunk layout as data_pipeline/pipeline/chunk_and_embed.py
    build_faculty_chunks(), so chatbot retrieval behaves identically."""

    def join_list(val):
        return ", ".join(v for v in val if v) if isinstance(val, list) else ""

    def has(val):
        return val is not None and str(val).strip() != ""

    chunks = []
    parts = []
    if has(row.get("name")):
        parts.append(row["name"])
    if has(row.get("designation")):
        parts.append(f"is working as {row['designation']}")
    if has(row.get("department")):
        parts.append(f"in the Department of {row['department']}")
    q = join_list(row.get("educational_qualifications"))
    if has(q):
        parts.append(f"with qualifications in {q}")
    exp = join_list(row.get("past_experience"))
    if has(exp):
        parts.append(f"with professional experience in {exp}")
    if parts:
        chunks.append(("01_profile", " ".join(parts) + "."))

    interests = join_list(row.get("areas_of_interest"))
    if has(interests):
        chunks.append(("02_interests", f"Areas of academic and research interest include {interests}."))
    subjects = join_list(row.get("subjects_taught"))
    if has(subjects):
        chunks.append(("03_subjects", f"Subjects taught include {subjects}."))
    ach = join_list(row.get("achievements"))
    if has(ach):
        chunks.append(("04_achievements", f"Notable achievements include {ach}."))
    if has(row.get("research")):
        chunks.append(("05_research", f"Research work focuses on {row['research'].strip()}."))
    return chunks


def _delete_embeddings(faculty_id: str):
    supabase.table("unified_embeddings").delete() \
        .eq("source_type", "faculty_biodata").eq("source_id", faculty_id).execute()


def _refresh_embeddings(faculty_id: str):
    """Background task: replace this faculty's embedding chunks with fresh ones."""
    try:
        # Lazy import: reuses the embedding model the RAG engine already loaded.
        from RAG_ENGINE.src.embedder import model

        row = supabase.table("faculty_biodata").select("*") \
            .eq("faculty_id", faculty_id).execute().data
        _delete_embeddings(faculty_id)
        if not row:
            return
        row = row[0]
        records = []
        for idx, (chunk_type, text) in enumerate(_build_chunks(row)):
            records.append({
                "source_type": "faculty_biodata",
                "source_id": faculty_id,
                "chunk_type": chunk_type,
                "chunk_index": idx,
                "raw_text": text,
                "metadata": {
                    "entity": "faculty",
                    "name": row.get("name"),
                    "department": row.get("department"),
                },
                "embedding": model.encode(text).tolist(),
            })
        if records:
            supabase.table("unified_embeddings").insert(records).execute()
    except Exception:
        print(f"FACULTY EMBEDDING REFRESH ERROR ({faculty_id}):\n", traceback.format_exc())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", dependencies=[require_admin()])
def list_faculty():
    data = supabase.table("faculty_biodata").select("*").execute().data or []

    def sort_key(r):
        fid = r.get("faculty_id", "")
        return (0, int(fid[3:])) if fid.startswith("FAC") and fid[3:].isdigit() else (1, 0)

    data.sort(key=sort_key)
    return {"count": len(data), "faculty": data}


@router.post("", dependencies=[require_admin()])
def add_faculty(payload: FacultyPayload, background_tasks: BackgroundTasks):
    row = _to_row(payload)
    row["faculty_id"] = _next_faculty_id()
    try:
        inserted = supabase.table("faculty_biodata").insert(row).execute().data[0]
    except Exception as e:
        print("FACULTY ADD ERROR:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Could not add faculty: {e}")

    background_tasks.add_task(_refresh_embeddings, inserted["faculty_id"])
    return {"status": "ok", "faculty": inserted}


@router.put("/{faculty_id}", dependencies=[require_admin()])
def update_faculty(faculty_id: str, payload: FacultyPayload, background_tasks: BackgroundTasks):
    exists = supabase.table("faculty_biodata").select("faculty_id") \
        .eq("faculty_id", faculty_id).execute().data
    if not exists:
        raise HTTPException(status_code=404, detail="Faculty not found.")

    row = _to_row(payload)
    try:
        updated = supabase.table("faculty_biodata").update(row) \
            .eq("faculty_id", faculty_id).execute().data[0]
    except Exception as e:
        print("FACULTY UPDATE ERROR:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Could not update faculty: {e}")

    background_tasks.add_task(_refresh_embeddings, faculty_id)
    return {"status": "ok", "faculty": updated}


@router.delete("/{faculty_id}", dependencies=[require_admin()])
def delete_faculty(faculty_id: str):
    exists = supabase.table("faculty_biodata").select("faculty_id") \
        .eq("faculty_id", faculty_id).execute().data
    if not exists:
        raise HTTPException(status_code=404, detail="Faculty not found.")

    try:
        _delete_embeddings(faculty_id)
        # subjects rows for this faculty are removed by ON DELETE CASCADE
        supabase.table("faculty_biodata").delete().eq("faculty_id", faculty_id).execute()
    except Exception as e:
        print("FACULTY DELETE ERROR:\n", traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Could not delete faculty: {e}")

    return {"status": "ok", "deleted": faculty_id}