"""
Admin: Circular upload.  Uses the data_pipeline modules; vectors go to unified_embeddings.

  POST   /admin/circulars/extract  -> PDF -> Gemini -> row to REVIEW (nothing saved)
  POST   /admin/circulars/save     -> admin-approved row -> chunk -> embed -> unified_embeddings
  GET    /admin/circulars/list     -> circulars currently stored
  DELETE /admin/circulars/{id}     -> remove a circular's vectors
"""
import os
import re
import sys
import tempfile
import uuid
from typing import List, Optional

from fastapi import APIRouter, File, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.auth_utils import require_admin

# data_pipeline modules import each other as `pipeline.*`, so its folder must be on sys.path
_PIPELINE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data_pipeline",
)
if _PIPELINE_ROOT not in sys.path:
    sys.path.insert(0, _PIPELINE_ROOT)

from pipeline.extract_text import extract_circular, normalize_circular   # noqa: E402
from pipeline.chunk_and_embed import embed_circular                      # noqa: E402
from pipeline.load_to_db import fetch_circular_summaries, delete_circular_embeddings  # noqa: E402
from pipeline.utils import CIRCULAR_CATEGORIES                           # noqa: E402

router = APIRouter(prefix="/admin/circulars", tags=["Admin - Circulars"])

MAX_PDF_BYTES = 25 * 1024 * 1024  # 25 MB
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CircularRow(BaseModel):
    id: Optional[str] = None          # client-side row id, ignored
    circular_no: Optional[str] = ""
    title: str = ""
    category: Optional[str] = "general"
    circular_date: Optional[str] = ""
    issued_by: Optional[str] = ""
    applies_to: Optional[str] = ""
    summary: Optional[str] = ""
    full_text: str = ""
    file_name: Optional[str] = ""


class SaveCircularsRequest(BaseModel):
    events: List[CircularRow] = Field(default_factory=list)   # key name matches the admin UI


@router.post("/extract", dependencies=[require_admin()])
async def extract(file: UploadFile = File(...)):
    if (file.filename or "").lower().rsplit(".", 1)[-1] != "pdf":
        return JSONResponse(status_code=400, content={"detail": "Only PDF files are accepted."})

    contents = await file.read()
    if not contents:
        return JSONResponse(status_code=400, content={"detail": "Uploaded file is empty."})
    if len(contents) > MAX_PDF_BYTES:
        return JSONResponse(status_code=413, content={"detail": "PDF too large (max 25 MB)."})

    # tempfile works on Windows and Linux; the user's filename is never used in the path
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    try:
        tmp.write(contents)
        tmp.close()
        raw = await run_in_threadpool(extract_circular, tmp.name)
    except Exception as e:
        import traceback
        print("CIRCULAR EXTRACT ERROR:\n", traceback.format_exc())
        return JSONResponse(status_code=500, content={"detail": f"Gemini extraction failed: {e}"})
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass

    row, warnings = normalize_circular(raw, file_name=file.filename or "")
    row["id"] = str(uuid.uuid4())
    return {
        "filename": file.filename,
        "count": 1,
        "events": [row],            # the admin UI reads `events`
        "warnings": warnings,
        "categories": CIRCULAR_CATEGORIES,
    }


@router.post("/save", dependencies=[require_admin()])
async def save(payload: SaveCircularsRequest):
    if not payload.events:
        return JSONResponse(status_code=400, content={"detail": "No circular to save."})

    # validate everything first so a bad row never causes a half-save
    for r in payload.events:
        label = r.title[:40] or "(untitled)"
        if not r.title.strip():
            return JSONResponse(status_code=400, content={"detail": "Every circular needs a title."})
        if not r.full_text.strip():
            return JSONResponse(status_code=400, content={"detail": f"'{label}' has no body text."})
        if r.circular_date and not DATE_RE.match(r.circular_date.strip()):
            return JSONResponse(
                status_code=400,
                content={"detail": f"'{label}': date must be YYYY-MM-DD (got '{r.circular_date}')."},
            )

    saved, total_chunks = 0, 0
    for r in payload.events:
        row = r.model_dump()
        row["category"] = (row.get("category") or "general").strip().lower().replace(" ", "_")
        row["circular_date"] = (row.get("circular_date") or "").strip() or None
        try:
            result = await run_in_threadpool(embed_circular, row)
        except Exception as e:
            import traceback
            print("CIRCULAR SAVE ERROR:\n", traceback.format_exc())
            return JSONResponse(
                status_code=500,
                content={"detail": f"Could not save '{r.title[:40]}': {e}. Press Save again to retry."},
            )
        saved += 1
        total_chunks += result["chunks"]

    return {"status": "ok", "inserted": saved, "chunks_embedded": total_chunks}


@router.get("/list", dependencies=[require_admin()])
async def list_all():
    rows = await run_in_threadpool(fetch_circular_summaries)
    return {"circulars": [
        {"circular_id": r["source_id"], **(r.get("metadata") or {}), "created_at": r.get("created_at")}
        for r in rows
    ]}


@router.delete("/{circular_id}", dependencies=[require_admin()])
async def remove(circular_id: str):
    if not re.match(r"^CIR-[0-9a-f]{12}$", circular_id):
        return JSONResponse(status_code=400, content={"detail": "Invalid circular id."})
    await run_in_threadpool(delete_circular_embeddings, circular_id)
    return {"status": "deleted", "circular_id": circular_id}