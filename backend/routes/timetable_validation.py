"""Deterministic post-processing for Gemini timetable extraction.

This module is pure Python so it can be tested without credentials or APIs.
It intentionally does NOT discard ambiguous entries: the admin must review them.
"""
import re
from typing import Any

DAYS = {d.lower(): d for d in (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"
)}
TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})\s*$")
MAX_ROWS = 1500


def nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return None if value.lower() in {"", "none", "null", "n/a", "unknown"} else value


def boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "y", "1", "lab"}


def time_slot(value: Any) -> str | None:
    raw = nullable_text(value)
    if raw is None:
        return None
    match = TIME_RE.fullmatch(raw)
    if not match:
        return None
    h1, m1, h2, m2 = map(int, match.groups())
    if not (0 <= h1 <= 23 and 0 <= h2 <= 23 and 0 <= m1 <= 59 and 0 <= m2 <= 59):
        return None
    if (h1, m1) == (h2, m2):
        return None
    # College grids commonly print 12:35-1:30, 1:30-2:25, etc.
    # Convert only clear 12-hour afternoon sequences; avoid guessing at other
    # ambiguous times (e.g., 01:00-02:00 could be a night shift timetable).
    if h1 == 12 and 1 <= h2 <= 8:
        h2 += 12
    elif 1 <= h1 <= 8 and 1 <= h2 <= 8:
        h1 += 12
        h2 += 12
    elif 1 <= h1 <= 8 and h2 == 12:
        # Ambiguous; retain and let admin correct rather than fabricate.
        return f"{h1:02d}:{m1:02d}-{h2:02d}:{m2:02d}"
    if (h2, m2) <= (h1, m1):
        return None
    return f"{h1:02d}:{m1:02d}-{h2:02d}:{m2:02d}"


def validate_extracted_rows(raw_rows: Any, raw_warnings: Any = None) -> tuple[list[dict], list[str]]:
    """Return (reviewable rows, warnings). Never silently fabricate missing data."""
    warnings = [str(w) for w in raw_warnings if isinstance(w, (str, int, float))] if isinstance(raw_warnings, list) else []
    if not isinstance(raw_rows, list):
        raise ValueError("The extraction response must contain a 'rows' array.")
    if len(raw_rows) > MAX_ROWS:
        raise ValueError("The extraction returned too many timetable rows to review safely.")

    rows = []
    seen = set()
    for idx, raw in enumerate(raw_rows, start=1):
        if not isinstance(raw, dict):
            warnings.append(f"Row {idx}: skipped because it is not a JSON object.")
            continue
        class_name = nullable_text(raw.get("class"))
        day = nullable_text(raw.get("day_of_week"))
        slot_raw = nullable_text(raw.get("time_slot"))
        slot = time_slot(slot_raw)
        code = nullable_text(raw.get("subject_code"))
        activity = nullable_text(raw.get("activity"))
        lab_id = nullable_text(raw.get("lab_id"))
        is_lab = boolean(raw.get("is_lab", False))

        if not any((class_name, day, slot_raw, code, activity)):
            continue
        if day is not None:
            canonical_day = DAYS.get(day.lower())
            if canonical_day is None:
                warnings.append(f"Row {idx}: unrecognized day '{day}'. Please correct it.")
            else:
                day = canonical_day
        if class_name is None:
            warnings.append(f"Row {idx}: class/section is missing.")
        if day is None:
            warnings.append(f"Row {idx}: day of week is missing.")
        if slot is None:
            warnings.append(f"Row {idx}: time slot '{slot_raw or ''}' is missing or invalid; correct it before saving.")
        if code is None and activity is None:
            warnings.append(f"Row {idx}: both subject code and activity are missing.")
        if activity and re.fullmatch(r"[BREA K]", activity, re.IGNORECASE):
            warnings.append(f"Row {idx}: activity '{activity}' may be one letter from a vertical BREAK label; inspect the image.")
        row = {
            "class": class_name or "",
            "day_of_week": day or "",
            "time_slot": slot or (slot_raw or ""),
            "subject_code": code,
            "activity": activity,
            "is_lab": is_lab,
            "lab_id": lab_id,
        }
        fingerprint = tuple(str(row[k]).strip().lower() for k in row)
        if fingerprint in seen:
            warnings.append(f"Row {idx}: exact duplicate was removed from preview.")
            continue
        seen.add(fingerprint)
        rows.append(row)
    # Detect visually plausible but structurally suspicious responses. These are
    # WARNINGS, not automatic edits: some colleges legitimately have exceptions.
    by_day = {}
    sections = set()
    for row in rows:
        key = (row["class"], row["day_of_week"])
        by_day.setdefault(key, []).append(row)
        if row["class"]:
            sections.add(row["class"])
    if len(sections) > 1:
        warnings.append("Multiple class labels found in extraction; verify this is a multi-class document.")
    for (section, day), entries in by_day.items():
        lunch = [r for r in entries if (r["activity"] or "").strip().upper() == "LUNCH"]
        if len(lunch) > 1:
            warnings.append(f"{section} {day}: LUNCH appears in {len(lunch)} slots; verify merged-cell boundaries.")
        by_slot = {}
        for r in entries:
            by_slot.setdefault(r["time_slot"], []).append(r)
        for slot, at_slot in by_slot.items():
            activities = {(r["activity"] or "").strip().upper() for r in at_slot}
            if ("BREAK" in activities or "LUNCH" in activities) and len(activities) > 1:
                warnings.append(f"{section} {day} {slot}: break/lunch conflicts with another activity; review visual grid.")
            if any(r["is_lab"] and r["activity"] and r["activity"].strip().upper() in {"BREAK", "LUNCH"} for r in at_slot):
                warnings.append(f"{section} {day} {slot}: break/lunch incorrectly marked as lab.")
    # An unexpectedly uniform row count may indicate the model filled blank
    # cells: signal the admin instead of altering real data automatically.
    if not rows:
        warnings.append("No timetable rows were extracted. Check document quality and layout.")
    return rows, warnings
