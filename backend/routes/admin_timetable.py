import os
import json
import re
import base64
import logging
from typing import Any

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel

from google import genai
from google.genai import types

from RAG_ENGINE.src.db import get_supabase_client
from backend.auth_utils import get_current_user
from backend.routes.timetable_validation import validate_extracted_rows
from backend.routes.timetable_grid_extraction import extract_grid_first, parse_json
from backend.routes.timetable_fullpage_extraction import extract_fullpage_days
import asyncio

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/admin/timetable",
    tags=["Admin Timetable"]
)


# ============================================================
# CONFIG
# ============================================================

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_UPLOAD_BYTES = int(os.getenv("TIMETABLE_MAX_UPLOAD_BYTES", str(12 * 1024 * 1024)))


def get_gemini_client():
    """Initialize only when extraction is requested; allow API startup without the key."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="Timetable extraction is not configured on this server.")
    return genai.Client(api_key=api_key)


TIMETABLE_TABLE = "timetable"


ALLOWED_EXTENSIONS = {
    "pdf",
    "png",
    "jpg",
    "jpeg",
    "webp"
}


MIME_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp"
}


# ============================================================
# REQUEST MODEL FOR SAVE
# ============================================================

class TimetableSaveRequest(BaseModel):
    rows: list[dict[str, Any]]


# ============================================================
# HELPERS
# ============================================================

def get_extension(filename: str) -> str:

    if not filename:
        return ""

    return (
        filename
        .rsplit(".", 1)[-1]
        .lower()
    )


def clean_json_response(text: str) -> str:

    text = text.strip()

    # Remove markdown code fences if Gemini returns them.
    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    return text.strip()


def normalize_bool(value):

    if isinstance(value, bool):
        return value

    if value is None:
        return False

    value = str(value).strip().lower()

    return value in {
        "true",
        "yes",
        "y",
        "1",
        "lab"
    }


def normalize_row(row: dict) -> dict:

    return {
        "class": str(
            row.get("class", "")
        ).strip(),

        "day_of_week": str(
            row.get("day_of_week", "")
        ).strip(),

        "time_slot": str(
            row.get("time_slot", "")
        ).strip(),

        "subject_code": str(
            row.get("subject_code", "")
        ).strip(),

        "activity": str(
            row.get("activity", "")
        ).strip(),

        "is_lab": normalize_bool(
            row.get("is_lab", False)
        ),

        "lab_id": (
            str(row.get("lab_id", "")).strip()
            or None
        )
    }


# ============================================================
# GEMINI EXTRACTION PROMPT
# ============================================================

EXTRACTION_PROMPT = """
You are an expert document and visual table extraction system.

You are given a college timetable PDF/image.

The timetable may be:
- scanned
- rotated
- visually complex
- split into multiple sections
- accompanied by subject/faculty information
- containing normal classes, labs, library, mentoring, technical club, project work, electives, placement activities, lunch, breaks, etc.

Your job is to extract the ACTUAL CLASS TIMETABLE.

CRITICAL VISUAL GRID AUDIT — PERFORM BEFORE PRODUCING JSON:
1. Identify the grid's exact COLUMN HEADERS, DAY ROWS and BORDERS; ignore the legend and important-dates box.
2. Inspect EACH DAY independently from left to right. Never fill a day from another day's pattern.
3. Map each written subject to the DAY ROW and COLUMN(S) it actually occupies. A label centered inside a horizontally merged cell belongs to that entire visible cell, not to adjacent cells.
4. A vertically merged BREAK region may cover only SOME days. If a lab or other merged cell visibly crosses that time column on another day, DO NOT insert BREAK on that day.
5. Similarly, never fill visually EMPTY afternoon columns, including a blank final period.
6. For each output row, confirm the subject code occurs INSIDE the actual grid cell for that same day and time. Use the subject legend only to translate codes into names and explicit lab locations.
7. Distinguish subject-code lookalikes character by character. A real cell labeled LA/PD must not be converted into the ordinary subject, a lab, or project work.
8. Treat a merged multi-period session as occupying ONLY the visible covered columns; represent each covered instructional period separately. Exclude any genuinely separate BREAK/LUNCH cells.
9. Review the Friday and Saturday rows separately immediately before finalizing; do not propagate a Friday project into Saturday or Saturday LA/PD into Friday.
10. Output time slots unambiguously in 24-HOUR time. Afternoon '1:30' means 13:30, '2:25' means 14:25, '3:20' means 15:20, '4:15' means 16:15.
11. Do not assume each weekday must have the same number of populated slots. Return fewer rows when cells are actually blank.
12. When uncertain, add a precise warning with day/time and preserve uncertainty instead of guessing.


Do NOT summarize the document.
Do NOT describe the document.
Do NOT invent missing information.

Return ONLY valid JSON.

==================================================
OUTPUT FORMAT
==================================================

{
  "rows": [
    {
      "class": "6A",
      "day_of_week": "Monday",
      "time_slot": "09:00-09:55",
      "subject_code": "22CS61",
      "activity": "",
      "is_lab": false,
      "lab_id": null
    }
  ],
  "warnings": []
}

==================================================
CORE EXTRACTION RULES
==================================================

1. IDENTIFY THE CLASS / SECTION

Identify the class or section represented by the actual timetable.

Examples:
6A
6B
7A
7D
VII(D)

Preserve the exact class/section shown in the timetable.

Do not invent or normalize the class name unless required to remove obvious formatting noise.

If the class cannot be determined confidently:
- use null
- add a warning

--------------------------------------------------

2. EXTRACT THE ACTUAL TIMETABLE GRID

Extract the actual timetable represented by the DAY × TIME-SLOT grid.

Each actual timetable slot/cell should become one row when it contains a meaningful timetable entry.

Do NOT create rows merely because text appears visually inside a merged cell.

Do NOT split a visually merged label into multiple semantic activities.

Do NOT treat text from the subject/faculty reference table as timetable cells.

The visual table structure, borders, row boundaries, column boundaries, and merged cells are extremely important.

Use the POSITION of the cell in the timetable to determine its day and time slot.

--------------------------------------------------

3. DAYS

Extract the day exactly as one of:

Monday
Tuesday
Wednesday
Thursday
Friday
Saturday

Do not create timetable rows for unrelated dates or important-date sections.

--------------------------------------------------

4. TIME SLOTS

Extract the exact time slot associated with each timetable cell.

Every time_slot MUST use this format:

HH:MM-HH:MM

Examples:

09:00-09:55
09:55-10:05
10:05-11:00
11:00-11:55
11:55-12:35
12:35-13:30
13:30-14:25
14:25-15:20
15:20-16:15

Normalize obvious formatting variations into this format.

For example:

"3:20:4:15"

is INVALID.

It must be:

"03:20-04:15"

Never use a colon between the start and end times.

Never output:

HH:MM:HH:MM

If the time cannot be determined confidently:
- use null
- add a warning

--------------------------------------------------

5. SUBJECT CODE

Extract the subject code only when it is visibly present inside the actual timetable cell.

Examples:

22CS71
22CS72
22CS73
22CS75
22CSE77X

If no subject code is visible in the timetable cell:
use null.

Do NOT invent subject codes.

Do NOT assign a subject code merely because a similar subject exists in the subject reference table.

The actual timetable cell is the primary source.
CRITICAL SUBJECT-CODE PRIORITY RULE:

The subject code visibly printed INSIDE the timetable grid cell is authoritative.

If a subject code is visible in an actual timetable cell, copy that code EXACTLY as it appears.

NEVER replace, correct, expand, shorten, or reinterpret that code using:
- the subject reference table
- the subject legend
- the faculty reference table
- common timetable patterns
- expected subject codes
- similar-looking subject codes

The reference table may ONLY be used to identify the subject name/activity AFTER the
subject code has been read from the timetable cell.

For example, if the timetable cell visibly contains:

"22CS78"

and the reference table contains both:

"22CS78 - PPL Interview Preparedness Course"
"22CSP78 - Major Project Phase - 2"

the extracted subject_code MUST remain:

"22CS78"

Do NOT change it to "22CSP78".

If the visible timetable cell contains an ambiguous or unclear code, preserve the
code exactly as visually read if possible. If it cannot be read confidently, use
null and add a warning rather than guessing from the reference table.

NEVER use the reference table to resolve an ambiguous visual code into a different
code.
--------------------------------------------------

6. ACTIVITY / SUBJECT NAME

The "activity" field should contain the human-readable subject or activity shown in the timetable cell.

Examples:

High Performance Computing
Cyber Security
Cloud Computing
Green Computing
Full Stack Development
Library
Technical Club
Mentoring
Placement Practice Lab
Lunch
Project Phase-II
Elective
Learning Assessment/Partial Delivery

If the cell contains a subject code but the subject name cannot be determined reliably:
- activity may be null

If the cell contains an activity with no subject code:
- subject_code = null
- activity = the visible activity

Do not invent activity names.

--------------------------------------------------

7. LABS

If the timetable cell represents a laboratory session:

"is_lab": true

Otherwise:

"is_lab": false

Only populate lab_id when an explicit laboratory identifier is visible or can be directly read from the timetable.

Examples:

Lab 6
Lab 1, 2 & 5
Lab 3 & 4

Never invent a lab ID.

If a lab session spans multiple timetable slots because of a merged cell, preserve the session across the actual occupied time slots.

However, NEVER assign a break column to the lab session.

--------------------------------------------------

8. EMPTY CELLS

Do NOT create rows for genuinely empty timetable cells.

An empty cell means there is no visible class/activity assigned to that day/time slot.

--------------------------------------------------

9. BREAKS AND LUNCH

If the timetable explicitly contains a break, preserve it as an activity.

For example:

{
  "class": "6A",
  "day_of_week": "Monday",
  "time_slot": "09:55-10:05",
  "subject_code": null,
  "activity": "BREAK",
  "is_lab": false,
  "lab_id": null
}

If the timetable explicitly contains:

LUNCH

then preserve:

"activity": "LUNCH"

Do not invent a break or lunch where none is shown.

--------------------------------------------------

10. CRITICAL MERGED BREAK COLUMN RULE

A vertically merged BREAK label may visually spell B R E A K down several day rows.
That is ONE visual merged region, but the output must associate BREAK with EACH DAY
whose row is actually covered by that region. DO NOT create separate letter rows.
Do NOT output a single BREAK entry lacking a day.

IMPORTANT: the merged BREAK region may stop before a day where a lab crosses
through the usual break column. For such a day, DO NOT create a BREAK row.
Never assume an identical break on all six days: inspect its actual borders.

--------------------------------------------------

11. MERGED CELLS

The timetable may contain cells merged across multiple visual rows or columns.

Interpret merged cells according to the actual timetable grid.

A merged cell may represent:
- a lab spanning several periods
- a continuous activity
- a break
- lunch
- project work
- another timetable activity

Do NOT split a merged visual label into meaningless pieces.

At the same time, do not assume that every visually merged area occupies every time slot unless the table structure clearly shows that it does.

Use the timetable's row/column boundaries to determine the actual occupied periods.

--------------------------------------------------

12. MULTI-PERIOD LABS / SESSIONS

If a laboratory or other session spans multiple actual periods, represent it across the occupied timetable slots.

Example:

09:00-09:55 → Full Stack Development Lab
09:55-10:05 → BREAK
10:05-11:00 → Full Stack Development Lab
11:00-11:55 → Full Stack Development Lab

Do NOT include the break slot as part of the lab.

Never allow a merged lab cell to overwrite a clearly separate BREAK/LUNCH column.

--------------------------------------------------

13. SUBJECT REFERENCE / LEGEND

The bottom section of the document may contain a reference table containing:

- subject codes
- subject names
- faculty names
- faculty initials
- classroom/lab
- email IDs
- departments

This is REFERENCE INFORMATION.

Do NOT create timetable rows from this reference table.

The actual timetable cell is ALWAYS the primary source.

You may use the subject reference table ONLY to cross-check or resolve the meaning of a subject code that was already found in an actual timetable cell.

For example:

If an actual timetable cell contains:

22CS74

and the reference table says:

22CS74 → Cloud Computing

then "Cloud Computing" may be used as the activity.

But if an actual timetable cell contains only:

Library

do NOT search the reference table and invent a subject code.

Do NOT assign subject codes based only on similarity.

--------------------------------------------------

14. DO NOT CONFUSE OTHER DOCUMENT SECTIONS WITH TIMETABLE

The PDF/image may contain:

- class teacher information
- faculty names
- faculty emails
- subject reference table
- classroom information
- department information
- important dates
- examination dates
- semester dates
- signatures
- principal information
- coordinator information
- room numbers

These are NOT timetable rows.

Extract ONLY the actual class timetable.

--------------------------------------------------

15. ACTIVITIES

Activities are valid timetable entries.

Examples include:

Library
Mentoring
Technical Club
Placement Practice Lab
Project
Major Project Phase - 2
Elective
Seminar
Lunch
Learning Assessment/Partial Delivery
Lab
Other explicitly shown activities

If an activity has no subject code:

subject_code = null

activity = visible activity name

Do not discard these rows merely because they are not normal subjects.

--------------------------------------------------

16. DO NOT GUESS

Never invent:

- class
- day
- time
- subject code
- subject name
- faculty
- lab ID
- activity

If a value cannot be determined confidently:

use null

and add a warning describing the ambiguity.

--------------------------------------------------

17. EXTRACT ALL RELEVANT ROWS

Extract ALL actual timetable rows before returning JSON.

Do not stop after the first few rows.

Do not return only examples.

Process the entire timetable.

If multiple timetable pages/classes are present, extract the timetable rows from all relevant pages/classes.

--------------------------------------------------

18. VISUAL POSITION HAS PRIORITY

When text recognition conflicts with the visual table structure, prioritize the visual position and cell boundaries.

Determine:

DAY
+
TIME SLOT
+
CELL CONTENT

from the actual timetable grid.

Do not assign a value to a cell merely because the text appears nearby.

Pay particular attention to:

- merged cells
- vertical text
- narrow columns
- break columns
- lab blocks
- multi-line subject names
- activities spanning multiple periods
- cells near the timetable boundaries

==================================================
EXAMPLES
==================================================

EXAMPLE 1 — NORMAL SUBJECT

If the timetable visually contains:

Monday
09:00-09:55
22CS71

and the subject reference table identifies 22CS71 as High Performance Computing:

{
  "class": "6A",
  "day_of_week": "Monday",
  "time_slot": "09:00-09:55",
  "subject_code": "22CS71",
  "activity": "High Performance Computing",
  "is_lab": false,
  "lab_id": null
}

--------------------------------------------------

EXAMPLE 2 — ACTIVITY WITHOUT SUBJECT CODE

If the timetable cell contains:

Library

then:

{
  "class": "6A",
  "day_of_week": "Wednesday",
  "time_slot": "11:00-11:55",
  "subject_code": null,
  "activity": "Library",
  "is_lab": false,
  "lab_id": null
}

--------------------------------------------------

EXAMPLE 3 — LAB

If the timetable cell contains:

22CSG73
Lab

and the timetable/reference information clearly identifies the laboratory as Lab 6:

{
  "class": "6A",
  "day_of_week": "Tuesday",
  "time_slot": "09:00-09:55",
  "subject_code": "22CSG73",
  "activity": "Full Stack Development Lab",
  "is_lab": true,
  "lab_id": "Lab 6"
}

--------------------------------------------------

EXAMPLE 4 — BREAK

If the timetable contains a dedicated:

09:55-10:05

BREAK

column:

{
  "class": "6A",
  "day_of_week": "Monday",
  "time_slot": "09:55-10:05",
  "subject_code": null,
  "activity": "BREAK",
  "is_lab": false,
  "lab_id": null
}

--------------------------------------------------

EXAMPLE 5 — VERTICAL BREAK LABEL

A single vertically rendered BREAK word spanning Monday, Wednesday and Thursday
means a BREAK row for each of those three days (when the column visually overlaps
those rows); it does NOT imply Tuesday has a break if Tuesday is occupied by a
merged lab across that column. Never output individual letters as rows.

--------------------------------------------------

EXAMPLE 6 — TIME FORMAT

If the source visually represents:

3:20 - 4:15

output:

"03:20-04:15"

Never output:

"3:20:4:15"

--------------------------------------------------

EXAMPLE 7 — LAB AROUND BREAK

If a lab visually spans:

09:00-09:55
09:55-10:05 BREAK
10:05-11:00
11:00-11:55

then the extraction should NOT assign the break period to the lab.

The output should represent:

09:00-09:55 → Lab
09:55-10:05 → BREAK
10:05-11:00 → Lab
11:00-11:55 → Lab

--------------------------------------------------

EXAMPLE 8 — NO SUBJECT CODE

If an actual timetable cell contains:

Placement Practice Lab

but no subject code:

{
  "subject_code": null,
  "activity": "Placement Practice Lab",
  "is_lab": false,
  "lab_id": null
}

Do not invent a subject code.

==================================================
VALIDATION BEFORE RETURNING JSON
==================================================

Before returning the final JSON, verify:

1. Every row belongs to the actual timetable grid.

2. Every row has a valid day.

3. Every row has a valid time slot.

4. Every time_slot follows:
   HH:MM-HH:MM

5. No time slot contains:
   HH:MM:HH:MM

6. No rows contain meaningless activities such as:
   B
   R
   E
   A
   K

7. Vertically rendered BREAK labels are treated as one BREAK activity.

8. Subject codes are not invented.

9. Activities are not invented.

10. Reference-table rows are not included as timetable rows.

11. Faculty names/emails are not included as timetable rows.

12. Room numbers are not included as timetable rows.

13. Important dates/exam dates are not included as timetable rows.

14. Lab IDs are only populated when explicitly supported.

15. Merged cells are interpreted using the visual table structure.

16. Break/lunch periods are not accidentally absorbed into adjacent classes or labs.

17. The entire timetable has been processed.

18. Any genuinely uncertain extraction has a warning.

==================================================
WARNINGS
==================================================

Add warnings for:

- unreadable text
- ambiguous class
- ambiguous day
- ambiguous time slot
- ambiguous subject code
- ambiguous activity
- unclear lab information
- unclear merged-cell boundaries
- cells whose day/time could not be determined
- any other information that could not be confidently extracted

Warnings must describe the issue briefly.

==================================================

Return JSON ONLY.

Do not include markdown.

Do not include explanations outside the JSON.
"""
# ============================================================
# EXTRACT ENDPOINT
# ============================================================

@router.post("/extract")
async def extract_timetable(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):

    # --------------------------------------------------------
    # Check admin access
    # --------------------------------------------------------

    if getattr(current_user, "role", None) != "admin":

        raise HTTPException(
            status_code=403,
            detail="Admin access required."
        )


    # --------------------------------------------------------
    # Check file
    # --------------------------------------------------------

    filename = file.filename or ""

    extension = get_extension(filename)

    if extension not in ALLOWED_EXTENSIONS:

        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. "
                "Upload PDF, PNG, JPG, JPEG, or WEBP."
            )
        )


    # --------------------------------------------------------
    # Read file
    # --------------------------------------------------------

    # Read one byte beyond the limit so oversized uploads cannot exhaust memory.
    file_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Timetable document exceeds the upload size limit.")

    if not file_bytes:

        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )


    # Reject obvious extension/content mismatches before sending to Gemini.
    if extension == "pdf" and not file_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="File content is not a valid PDF header.")
    if extension == "png" and not file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="File content does not match PNG format.")
    if extension in {"jpg", "jpeg"} and not file_bytes.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="File content does not match JPEG format.")
    if extension == "webp" and not (file_bytes.startswith(b"RIFF") and file_bytes[8:12] == b"WEBP"):
        raise HTTPException(status_code=400, detail="File content does not match WEBP format.")

    mime_type = MIME_TYPES[extension]


    # --------------------------------------------------------
    # Gemini Vision
    # --------------------------------------------------------

    mode = os.getenv("TIMETABLE_EXTRACTION_MODE", "fullpage").strip().lower()
    client = None if mode == "local" else get_gemini_client()
    try:
        if mode == "local":
            from backend.services.timetable_parser.local_pipeline import extract_local_timetable
            extracted = await asyncio.to_thread(extract_local_timetable, file_bytes, filename)
        elif mode == "fullpage":
            extracted = await asyncio.to_thread(
                extract_fullpage_days, client, GEMINI_MODEL, file_bytes, mime_type, filename
            )
        elif mode == "grid":
            extracted = await asyncio.to_thread(
                extract_grid_first, client, GEMINI_MODEL, file_bytes, mime_type
            )
        elif mode == "legacy":
            # Preserve V2 as a fallback for testing, never automatically
            # substitute a bad result for a failed grid extraction.
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=[types.Part.from_bytes(data=file_bytes, mime_type=mime_type), EXTRACTION_PROMPT],
            )
            extracted = parse_json(response.text)
        else:
            raise HTTPException(status_code=500, detail="Invalid timetable extraction mode.")
    except HTTPException:
        raise
    except ValueError as exc:
        logger.warning("Timetable image/layout validation failed: %s", exc)
        raise HTTPException(status_code=422, detail="Timetable document could not be read reliably. Check the image and try again.")
    except Exception:
        logger.exception("Timetable extraction provider failed")
        raise HTTPException(status_code=503, detail="Timetable extraction is temporarily unavailable. Try again later.")

    # --------------------------------------------------------
    # Validate and normalize for admin review (do not auto-save)
    # --------------------------------------------------------
    try:
        if not isinstance(extracted, dict):
            raise ValueError("Extraction must return a JSON object.")
        rows, warnings = validate_extracted_rows(
            extracted.get("rows"), extracted.get("warnings", [])
        )
    except ValueError:
        logger.warning("Timetable extraction schema invalid")
        raise HTTPException(status_code=502, detail="The extraction service returned an invalid timetable structure.")

    if not rows:
        raise HTTPException(status_code=422, detail="No valid timetable entries were extracted. Check the original document.")
    return {"success": True, "rows": rows, "warnings": warnings, "filename": filename}


# ============================================================
# REVIEW + SAFE SAVE ENDPOINTS
# ============================================================
from backend.services.timetable_save_validation import (
    validate_save_rows, validate_department, is_subgroup
)
from fastapi import Query


def _admin_only(user):
    if getattr(user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")


def _revision(supabase, section):
    result = supabase.rpc(
        "timetable_class_revision", {"p_class": section}
    ).execute()
    revision = result.data
    if not isinstance(revision, str) or len(revision) != 32:
        raise RuntimeError("Invalid class revision; check installed SQL RPC")
    return revision


@router.post("/validate")
async def validate_timetable_save(
    request: TimetableSaveRequest,
    current_user=Depends(get_current_user),
):
    _admin_only(current_user)
    try:
        section, rows = validate_save_rows(request.rows)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"success": True, "class": section,
            "valid_rows": len(rows), "is_subgroup": is_subgroup(section)}


class TimetableReplaceRequest(TimetableSaveRequest):
    confirm_replace: bool = False
    confirm_subgroup: bool = False
    department: str
    expected_revision: str


@router.get("/existing")
async def existing_timetable(
    class_name: str = Query(min_length=1, max_length=80),
    current_user=Depends(get_current_user),
):
    _admin_only(current_user)
    try:
        supabase = get_supabase_client()
        revision = _revision(supabase, class_name)
        result = (
            supabase.table(TIMETABLE_TABLE)
            .select('class,day_of_week,time_slot,subject_code,activity,is_lab,lab_id,Dept')
            .eq('class', class_name).limit(501).execute()
        )
        rows = result.data or []
        if len(rows) > 500:
            raise RuntimeError('Existing timetable is too large to preview safely')
    except Exception:
        logger.exception("Could not read existing timetable or its revision")
        raise HTTPException(status_code=503, detail="Could not preview existing timetable or its revision.")
    return {"class": class_name, "rows": rows, "count": len(rows),
            "revision": revision, "is_subgroup": is_subgroup(class_name),
            "departments": sorted({str(r['Dept']) for r in rows if r.get('Dept')})}


@router.post("/save")
async def save_timetable(
    request: TimetableReplaceRequest,
    current_user=Depends(get_current_user),
):
    _admin_only(current_user)
    try:
        section, rows = validate_save_rows(request.rows)
        department = validate_department(request.department)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not request.confirm_replace:
        raise HTTPException(status_code=409, detail="Explicit replacement confirmation required.")
    if is_subgroup(section) and not request.confirm_subgroup:
        raise HTTPException(status_code=409, detail="Separate subgroup confirmation required.")
    if not re.fullmatch(r'[0-9a-f]{32}', request.expected_revision):
        raise HTTPException(status_code=422, detail="Invalid revision token; preview the class again.")
    # The database function locks the exact class, checks the revision inside
    # the same transaction, then replaces ONLY rows with class = section.
    # An RPC failure never triggers a client-side delete/insert fallback.
    try:
        result = get_supabase_client().rpc(
            "replace_class_timetable_v2",
            {"p_class": section, "p_rows": rows,
             "p_department": department,
             "p_expected_revision": request.expected_revision}
        ).execute()
    except Exception as exc:
        from backend.services.timetable_db_errors import classify_save_error

        status, detail = classify_save_error(exc)
        logger.exception(
            "Timetable replace RPC failed: status=%s", status
        )
        raise HTTPException(
            status_code=status,
            detail=detail,
        ) from exc

    inserted = result.data
    if not isinstance(inserted, int) or inserted != len(rows):
        logger.error("Unexpected save RPC result: %r", inserted)
        raise HTTPException(status_code=503, detail=(
            "Unexpected response. Check database before retrying; do not double-save."))
    return {"success": True, "inserted": inserted, "class": section,
            "department": department, "mode": "atomic_class_replace_v2",
            "subgroup_records_untouched": not is_subgroup(section)}
