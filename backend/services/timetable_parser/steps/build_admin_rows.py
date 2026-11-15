"""Convert experimental OCR JSON to NMIT admin extraction rows.

Usage:
    python experiments/qwen_timetable/build_admin_rows.py 7A
    python experiments/qwen_timetable/build_admin_rows.py 6A

This is an adapter, not the generalized PDF parser.
No database writes.
"""
import argparse
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent


def split_content(text):
    text = (text or "").strip()
    if not text:
        return "", "", False

    # Detect a course-code prefix, retaining elective alternatives.
    match = re.search(
        r"\b\d{2}[A-Z]{2,5}[A-Z]?\d{2,4}"
        r"(?:/[A-Z]?\d{2,4})*\b",
        text,
    )

    if not match:
        return "", text, "LAB" in text.upper()

    code = match.group(0)
    activity = (
        text[:match.start()] + " " + text[match.end():]
    ).strip(" -")

    is_lab = bool(
        re.search(r"\bLAB\b", text, re.I)
        or re.match(r"^22CSL", code, re.I)
    )

    return code, activity, is_lab


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("class_name")
    args = parser.parse_args()

    name = args.class_name
    folder = BASE / f"cells_{name}"
    source = folder / f"timetable_{name}_final.json"

    data = json.loads(source.read_text())

    if not data.get("complete"):
        raise ValueError("OCR extraction is incomplete")

    # Read time slots extracted from the actual PDF.
    header_path = folder / "time_headers_resolved.json"

    if not header_path.exists():
        raise FileNotFoundError(
            f"Missing {header_path}. "
            "Run detect_time_headers.py and "
            "resolve_time_headers.py first."
        )

    header_data = json.loads(header_path.read_text())
    headers = header_data["headers"]

    if not header_data.get("all_resolved"):
        raise ValueError(
            "Some time headers are unresolved. "
            "Manual review required."
        )

    times = []

    for expected_slot, header in enumerate(headers, start=1):
        if header["slot"] != expected_slot:
            raise ValueError(
                f"Invalid header order at slot {expected_slot}"
            )

        times.append((
            header["start_time"],
            header["end_time"],
        ))

    max_slot = max(
        cell["last_slot"]
        for cell in data["cells"]
    )

    if max_slot != len(times):
        raise ValueError(
            f"Cell geometry contains {max_slot} slots, "
            f"but OCR detected {len(times)} time headers."
        )

    rows = []
    warnings = []

    for cell in data["cells"]:
        text = (cell.get("text") or "").strip()
        status = cell.get("status", "")

        if status != "recognized":
            warnings.append(
                f"{cell['day']} slots "
                f"{cell['first_slot']}-{cell['last_slot']}: "
                f"{status}; verify against source PDF"
            )

        if not text:
            # Empty periods aren't automatically saved as classes.
            continue

        subject_code, activity, is_lab = split_content(text)

        for slot in range(
            cell["first_slot"],
            cell["last_slot"] + 1,
        ):
            start, end = times[slot - 1]

            rows.append({
                "class": name,
                "day_of_week": cell["day"],
                "time_slot": f"{start}-{end}",
                "subject_code": subject_code,
                "activity": activity,
                "is_lab": is_lab,
                "lab_id": "",
            })

    output = {
        "rows": rows,
        "warnings": warnings,
    }

    target = folder / f"admin_rows_{name}.json"
    target.write_text(
        json.dumps(output, indent=2, ensure_ascii=False)
    )

    print(f"Class: {name}")
    print(f"Admin rows: {len(rows)}")
    print(f"Review warnings: {len(warnings)}")
    print(f"Saved: {target}")

    print("\nFirst five rows:")
    for row in rows[:5]:
        print(json.dumps(row))


if __name__ == "__main__":
    main()
