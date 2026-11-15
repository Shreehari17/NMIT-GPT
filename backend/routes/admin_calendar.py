"""
Admin: Academic Calendar upload pipeline.

Extraction reuses the project's existing Gemini-based logic as-is:
data_pipeline/pipeline/extract_text.py -> extract_academic_calendar()
(uploads the PDF to Gemini, prompts it for structured events, parses the
JSON it returns). We do not reimplement or change that logic here.

Flow:
  1. POST /admin/calendar/extract -> admin uploads the calendar PDF.
     We call the existing extract_academic_calendar() and return the
     events to the frontend for review. Nothing is written to the DB yet.
  2. Admin reviews/edits the rows in the frontend table.
  3. POST /admin/calendar/save -> admin submits the (possibly edited)
     list of events, which we validate and insert into the
     `academic_calendar` table in Supabase.
"""
import os
import re
import sys
import uuid
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.auth_utils import require_admin
from RAG_ENGINE.src.db import get_supabase_client

# ---------------------------------------------------------------------------
# Reuse the existing data_pipeline extraction logic (Gemini-based) directly,
# instead of duplicating it here.
# ---------------------------------------------------------------------------
_PIPELINE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data_pipeline",
)
if _PIPELINE_ROOT not in sys.path:
    sys.path.insert(0, _PIPELINE_ROOT)

from data_pipeline.pipeline.extract_text import extract_academic_calendar  # noqa: E402

router = APIRouter(prefix="/admin/calendar", tags=["Admin - Academic Calendar"])

supabase = get_supabase_client()

# Same event_type vocabulary the Gemini prompt in extract_text.py is asked
# to use, so the frontend dropdown and save validation stay in sync with it.
EVENT_TYPES = ["holiday", "exam", "academic", "co_curricular", "registration", "vacation"]
MAX_PDF_BYTES = 25 * 1024 * 1024  # 25 MB


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CalendarEvent(BaseModel):
    id: Optional[str] = None            # client-side row id, ignored on save
    event_date: str                     # expected "YYYY-MM-DD"
    event_name: str
    event_type: str = "academic"
    description: Optional[str] = ""


class SaveCalendarRequest(BaseModel):
    events: List[CalendarEvent] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/extract", dependencies=[require_admin()])
async def extract_calendar(file: UploadFile = File(...)):
    """Runs the existing Gemini-based extract_academic_calendar() on the
    uploaded PDF and returns rows for review. Nothing is saved yet."""
    suffix = (file.filename or "").lower().rsplit(".", 1)[-1]
    if suffix != "pdf":
        return JSONResponse(
            status_code=400,
            content={"detail": "The academic calendar extractor only accepts PDF files."},
        )

    contents = await file.read()
    if len(contents) > MAX_PDF_BYTES:
        return JSONResponse(status_code=413, content={"detail": "PDF too large (max 25 MB)."})
    if not contents:
        return JSONResponse(status_code=400, content={"detail": "Uploaded file is empty."})

    # Use our own generated name (uuid only) rather than folding the
    # user-supplied filename into the path, to rule out path traversal.
    tmp_path = f"/tmp/{uuid.uuid4().hex}.pdf"
    with open(tmp_path, "wb") as f:
        f.write(contents)

    try:
        raw_events = extract_academic_calendar(tmp_path)
    except Exception as e:
        import traceback
        print("CALENDAR EXTRACT ERROR:\n", traceback.format_exc())
        return JSONResponse(status_code=500, content={"detail": f"Gemini extraction failed: {e}"})
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    events = []
    warnings = []
    for e in raw_events:
        event_date = str(e.get("event_date") or "")
        event_name = str(e.get("event_name") or "")
        event_type = str(e.get("event_type") or "academic")
        events.append({
            "id": str(uuid.uuid4()),
            "event_date": event_date,
            "event_name": event_name,
            "event_type": event_type,
            "description": e.get("description") or "",
        })
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", event_date):
            warnings.append(f"Row '{event_name[:40]}' has an unrecognized date ('{event_date}') — please fix it before saving.")
        if event_type not in EVENT_TYPES:
            warnings.append(f"Row '{event_name[:40]}' has type '{event_type}', expected one of: {', '.join(EVENT_TYPES)}.")

    return {
        "filename": file.filename,
        "count": len(events),
        "events": events,
        "warnings": warnings,
        "event_types": EVENT_TYPES,
    }


@router.post("/save", dependencies=[require_admin()])
async def save_calendar(payload: SaveCalendarRequest):
    """Admin has reviewed/edited the extracted rows — replace the table with them.

    A newly uploaded academic calendar supersedes the old one entirely, so
    before inserting the new rows we wipe whatever was in `academic_calendar`
    previously. This runs only after validation passes, so a bad upload never
    wipes good data — and the delete + insert happen back-to-back so there's
    only a brief window where the table is empty rather than leaving stale
    and fresh events mixed together.
    """
    if not payload.events:
        return JSONResponse(status_code=400, content={"detail": "No events to save."})

    rows = []
    bad_rows = []
    for e in payload.events:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", e.event_date or ""):
            bad_rows.append(e.event_name)
            continue
        if not e.event_name.strip():
            continue
        rows.append({
            "event_date": e.event_date,
            "event_name": e.event_name.strip(),
            "event_type": (e.event_type or "academic").strip(),
            "description": (e.description or "").strip(),
        })

    if bad_rows:
        return JSONResponse(
            status_code=400,
            content={"detail": f"{len(bad_rows)} row(s) have an invalid date (expected YYYY-MM-DD): {', '.join(bad_rows[:5])}"},
        )

    if not rows:
        return JSONResponse(status_code=400, content={"detail": "No valid events to save."})

    # Wipe the old calendar now that we know the new one is valid. `.gte`
    # on the primary key matches every row regardless of its id.
    try:
        supabase.table("academic_calendar").delete().gte("id", 0).execute()
    except Exception as e:
        import traceback
        print("CALENDAR DELETE-OLD ERROR:\n", traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"detail": f"Could not clear the previous calendar, nothing was changed: {e}"},
        )

    try:
        supabase.table("academic_calendar").insert(rows).execute()
    except Exception as e:
        import traceback
        print("CALENDAR SAVE ERROR:\n", traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"detail": f"Old calendar was cleared but inserting the new one failed: {e}"},
        )

    return {"status": "ok", "inserted": len(rows), "replaced_old_calendar": True}
