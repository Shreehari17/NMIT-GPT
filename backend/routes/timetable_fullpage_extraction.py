"""V4: full-page timetable reading, no unverified AI-generated crop coordinates.

The first vision call reads the printed time header, then six independent day
calls receive the SAME full page plus a fixed list of allowable slots.  This
is deliberately fail-closed on obvious hallucinations and does not write data.
"""
from __future__ import annotations
import re
from typing import Any

from backend.routes.timetable_grid_extraction import DAYS, render_pages, provider_json
from backend.routes.timetable_validation import time_slot

HEADER_PROMPT = """You are transcribing a weekly college timetable image. Look at ONLY the
WEEKLY TIMETABLE GRID at the top, not the subject legend or IMPORTANT DATES box.
Copy the column headers in exact left-to-right order, including BREAK and LUNCH
columns. DO NOT make up time intervals. Interpret afternoon 1:30 as 13:30.
Identify the class/section printed above the grid. Return ONLY JSON:
{"class_label":"VII(A)","time_slots":["09:00-09:55","09:55-10:05"],"warnings":[]}
Those values are an OUTPUT FORMAT EXAMPLE, NOT a timetable to copy. Read the image.
If header is unreadable return time_slots:[]; do not guess.
"""

DAY_PROMPT = """Read ONLY the {day} ROW in this full-page college timetable image.
The column times are VERIFIED FROM THE HEADER in left-to-right order:
{slots}
The section ID for output is {section}.
IMPORTANT: The page has a timetable, an IMPORTANT DATES block on the right,
and a SUBJECT LEGEND below. Use legend ONLY to expand subject codes seen in the
grid. Do NOT read schedules from legend, other day rows, or dates box.

Read visually LEFT to RIGHT by grid column, not PDF OCR reading order.
Each printed column corresponds to exactly one listed time slot.
Merged horizontal activity cells cover ONLY their actual spanned columns.
Vertically merged BREAK/LUNCH cells may apply to multiple day rows, but ONLY
if they visibly intersect the {day} row. Never shift a subject to an adjacent
column. Never place a class or lab into a BREAK or LUNCH column unless the
actual cell visibly spans that column. Avoid duplicate lunch rows.

For any occupied cell, output one row per ACTUALLY occupied timetable period.
If a subject is illegible, output null subject_code and a warning; do not
invent a plausible subject. If a column is blank, emit no row for that slot.
Only use one of the supplied exact time_slot strings, copied verbatim.
Keep 7A/6A class label provided above; use it for EVERY row.
Return ONLY JSON with shape:
{{"rows":[{{"class":"{section}","day_of_week":"{day}",
"time_slot":"09:00-09:55","subject_code":null,"activity":"Library",
"is_lab":false,"lab_id":null}}],"warnings":[]}}
The row above is ONLY a FORMAT example; do not copy Library unless visible.
Before returning, independently check every row against the {day} image cells.
"""

_ROMAN = {"I":1,"II":2,"III":3,"IV":4,"V":5,"VI":6,"VII":7,"VIII":8}


def normalize_section(raw: Any, filename: str = "") -> str | None:
    """Accept printed 'VII(A) SEMESTER' or 7A, never coordinate arrays."""
    if not isinstance(raw, str):
        return None
    s = raw.upper().strip()
    m = re.search(r'\b(VIII|VII|VI|IV|III|II|V|I)\s*\(\s*([A-Z])\s*\)', s)
    if m:
        return f'{_ROMAN[m.group(1)]}{m.group(2)}'
    m = re.search(r'\b([1-8])\s*[-( ]?\s*([A-Z])\s*\)?\b', s)
    if m:
        return f'{m.group(1)}{m.group(2)}'
    return None


def validated_header(header: Any, filename: str = "") -> tuple[str,list[str],list[str]]:
    if not isinstance(header, dict):
        raise ValueError('Header extraction did not return an object')
    warnings = list(header.get('warnings') or []) if isinstance(header.get('warnings'), list) else []
    section = normalize_section(header.get('class_label'))
    filename_section = normalize_section(filename)
    if filename_section and section and filename_section != section:
        raise ValueError(f'Section in PDF ({section}) conflicts with file name ({filename_section}); verify document')
    if not section:
        # File name is a user-controlled hint, not proof; mark for review.
        if not filename_section:
            raise ValueError('Section label is unreadable; cannot assign timetable records')
        section = filename_section
        warnings.append(f'Section label unreadable: used filename hint {section}; admin must confirm')
    proposed = header.get('time_slots')
    if not isinstance(proposed, list) or not 4 <= len(proposed) <= 14:
        raise ValueError('Time header missing or implausible; no timetable rows accepted')
    slots = []
    previous_end = None
    for value in proposed:
        normalized = time_slot(value)
        if not normalized or normalized in slots:
            raise ValueError(f'Invalid/duplicate printed time header: {value!r}')
        start, end = normalized.split('-')
        if previous_end is not None and start < previous_end:
            raise ValueError(f'Overlapping or unordered time headers near {value!r}')
        previous_end = end
        slots.append(normalized)
    return section, slots, warnings


def check_day_rows(result: Any, day: str, section: str, slots: list[str]) -> tuple[list[dict],list[str]]:
    if not isinstance(result, dict) or not isinstance(result.get('rows'), list):
        raise ValueError(f'{day} extraction returned invalid rows')
    rows=[]; warnings=[]; allowed=set(slots)
    for i, row in enumerate(result['rows'], 1):
        if not isinstance(row, dict):
            warnings.append(f'{day} row {i}: non-object rejected'); continue
        if row.get('day_of_week') != day:
            warnings.append(f'{day} row {i}: incorrect day rejected'); continue
        slot=time_slot(row.get('time_slot'))
        if slot not in allowed:
            warnings.append(f'{day} row {i}: invented/unrecognized slot {row.get("time_slot")!r} rejected'); continue
        if not row.get('subject_code') and not row.get('activity'):
            warnings.append(f'{day} {slot}: empty entry rejected'); continue
        row = dict(row)
        row['class'] = section
        row['time_slot'] = slot
        rows.append(row)
    warnings.extend(f'{day}: {w}' for w in result.get('warnings', []) if isinstance(w,str))
    return rows,warnings


def extract_fullpage_days(client, model: str, document: bytes, mime_type: str, filename: str) -> dict:
    pages=render_pages(document,mime_type)
    rows=[]; warnings=[]
    for page_no,image in enumerate(pages,1):
        header = provider_json(client,model,HEADER_PROMPT,[image])
        section,slots,header_warnings=validated_header(header,filename if len(pages)==1 else '')
        warnings.extend(f'Page {page_no}: {w}' for w in header_warnings)
        for day in DAYS:
            response=provider_json(client,model,DAY_PROMPT.format(day=day,section=section,slots=', '.join(slots)),[image])
            day_rows,day_warnings=check_day_rows(response,day,section,slots)
            rows.extend(day_rows)
            warnings.extend(f'Page {page_no}: {w}' for w in day_warnings)
        if not any(r['class']==section for r in rows):
            raise ValueError(f'Page {page_no}: no timetable entries extracted')
    return {'rows':rows,'warnings':warnings}
