import os
import json
import re
import base64
from typing import Any

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel

from google import genai
from google.genai import types

from RAG_ENGINE.src.db import get_supabase_client
from backend.auth_utils import get_current_user


router = APIRouter(
    prefix="/admin/timetable",
    tags=["Admin Timetable"]
)


# ============================================================
# CONFIG
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not set. Add it to your .env file."
    )


GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
)


gemini_client = genai.Client(
    api_key=GEMINI_API_KEY
)


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
12:35-01:30
01:30-02:25
02:25-03:20
03:20-04:15

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

The timetable may contain a vertically merged BREAK column.

The word BREAK may visually appear as individual letters such as:

B
R
E
A
K

These letters are NOT separate timetable activities.

They are parts of ONE vertically rendered "BREAK" label.

NEVER create rows with:

"B"
"R"
"E"
"A"
"K"

as activities.

Use the visual column borders and merged-cell structure to understand that these letters belong to ONE merged BREAK region.

If the visual timetable clearly shows that the entire 09:55-10:05 column is the break column, create exactly ONE BREAK row for that time slot:

{
  "time_slot": "09:55-10:05",
  "subject_code": null,
  "activity": "BREAK",
  "is_lab": false,
  "lab_id": null
}

Do NOT create separate rows for individual letters.

Do NOT treat letters from a vertically rendered merged label as subject codes, activities, or faculty information.

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

If the visual timetable shows:

B
R
E
A
K

vertically inside one merged column, these are NOT five different activities.

Create ONE row:

{
  "time_slot": "09:55-10:05",
  "subject_code": null,
  "activity": "BREAK",
  "is_lab": false,
  "lab_id": null
}

Never create:

"B"
"R"
"E"
"A"
"K"

as separate rows.

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

    file_bytes = await file.read()

    if not file_bytes:

        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )


    mime_type = MIME_TYPES[extension]


    # --------------------------------------------------------
    # Gemini Vision
    # --------------------------------------------------------

    try:

        response = gemini_client.models.generate_content(

            model=GEMINI_MODEL,

            contents=[

                types.Part.from_bytes(
                    data=file_bytes,
                    mime_type=mime_type
                ),

                EXTRACTION_PROMPT

            ]
        )

    except Exception as e:
        import traceback
        traceback.print_exc()

        raise HTTPException(
            status_code=503,
            detail=f"Gemini extraction temporarily unavailable: {str(e)}"
        )

    # --------------------------------------------------------
    # Parse Gemini response
    # --------------------------------------------------------

    try:

        raw_text = response.text or ""

        raw_text = clean_json_response(
            raw_text
        )

        extracted = json.loads(
            raw_text
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Gemini returned an invalid response. "
                f"Parsing error: {str(e)}"
            )
        )


    # --------------------------------------------------------
    # Normalize rows
    # --------------------------------------------------------

    raw_rows = extracted.get(
        "rows",
        []
    )

    rows = []

    for row in raw_rows:

        if not isinstance(row, dict):
            continue

        normalized = normalize_row(
            row
        )

        # Ignore completely empty rows.
        if not any(
            [
                normalized["class"],
                normalized["day_of_week"],
                normalized["time_slot"],
                normalized["subject_code"],
                normalized["activity"]
            ]
        ):
            continue

        rows.append(
            normalized
        )


    warnings = extracted.get(
        "warnings",
        []
    )

    return {
        "success": True,
        "rows": rows,
        "warnings": warnings,
        "filename": filename
    }


# ============================================================
# SAVE ENDPOINT
# ============================================================

@router.post("/save")
async def save_timetable(
    request: TimetableSaveRequest,
    current_user=Depends(get_current_user)
):

    # --------------------------------------------------------
    # Check admin
    # --------------------------------------------------------

    if getattr(current_user, "role", None) != "admin":

        raise HTTPException(
            status_code=403,
            detail="Admin access required."
        )


    rows = request.rows

    if not rows:

        raise HTTPException(
            status_code=400,
            detail="No timetable rows were provided."
        )


    # --------------------------------------------------------
    # Supabase
    # --------------------------------------------------------

    try:

        supabase = get_supabase_client()

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Could not connect to Supabase: {str(e)}"
        )


    # --------------------------------------------------------
    # Prepare rows
    # --------------------------------------------------------

    clean_rows = []

    for row in rows:

        clean_row = normalize_row(
            row
        )

        if not any(
            [
                clean_row["class"],
                clean_row["day_of_week"],
                clean_row["time_slot"],
                clean_row["subject_code"],
                clean_row["activity"]
            ]
        ):
            continue

        clean_rows.append(
            clean_row
        )


    if not clean_rows:

        raise HTTPException(
            status_code=400,
            detail="No valid timetable rows found."
        )


    # --------------------------------------------------------
    # Insert into timetable_updated
    # --------------------------------------------------------

    try:

        result = (
            supabase
            .table(TIMETABLE_TABLE)
            .insert(clean_rows)
            .execute()
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Could not save timetable to "
                f"{TIMETABLE_TABLE}: {str(e)}"
            )
        )


    inserted_count = len(
        result.data or clean_rows
    )


    return {
        "success": True,
        "inserted": inserted_count,
        "table": TIMETABLE_TABLE
    }