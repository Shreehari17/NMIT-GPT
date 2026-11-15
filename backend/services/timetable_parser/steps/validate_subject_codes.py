"""Validate dynamic timetable OCR against refined subject legends.

No automatic corrections. No backend or database writes.

Usage:
    python experiments/qwen_timetable/validate_subject_codes.py 6A
    python experiments/qwen_timetable/validate_subject_codes.py 7A
"""

import argparse
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent

CODE_GROUP = re.compile(
    r"(?<![A-Z0-9])"
    r"22[A-Z]{2,6}\d{2,4}[A-Z]?"
    r"(?:\s*/\s*\d{2,4}[A-Z]?)*",
    re.I,
)

FULL_CODE = re.compile(
    r"^(22[A-Z]{2,6})(\d{2,4}[A-Z]?)$",
    re.I,
)


def expand_group(group):
    """Expand abbreviated alternatives using the printed prefix."""
    parts = re.split(r"\s*/\s*", group.strip())
    match = FULL_CODE.fullmatch(parts[0])

    if not match:
        return []

    prefix = match.group(1).upper()
    codes = [parts[0].upper()]

    for part in parts[1:]:
        part = part.strip().upper()

        if re.fullmatch(r"\d{2,4}[A-Z]?", part):
            codes.append(prefix + part)

    return codes


def get_legend(folder):
    refined = folder / "subject_legend_refined.json"
    original = folder / "subject_legend_review.json"

    if refined.exists():
        data = json.loads(refined.read_text())

        # Section OCR is preferred. Do not automatically
        # union it with possibly incorrect original codes.
        codes = data.get("section_codes", [])
        source = "refined sections"
        uncertain = True

    elif original.exists():
        data = json.loads(original.read_text())
        codes = data.get("codes", [])
        source = "original legend OCR"
        uncertain = data.get("legend_ocr_uncertain", True)

    else:
        raise FileNotFoundError(
            "No subject legend found. Run legend OCR first."
        )

    return set(map(str.upper, codes)), source, uncertain


def validate(name):
    folder = BASE / f"dynamic_grid_{name}" / "page_1"

    ocr_path = folder / "dynamic_ocr.json"
    data = json.loads(ocr_path.read_text())

    if not data.get("complete"):
        raise ValueError("Dynamic OCR is incomplete.")

    legend, source, uncertain = get_legend(folder)

    findings = []
    checked = 0

    for cell in data["cells"]:
        text = str(cell.get("text") or "").strip()

        if not text:
            continue

        issues = []
        extracted_codes = []

        for match in CODE_GROUP.finditer(text):
            extracted_codes.extend(
                expand_group(match.group())
            )

        extracted_codes = list(dict.fromkeys(extracted_codes))

        for code in extracted_codes:
            if code not in legend:
                issues.append(
                    f"Code {code} not confirmed by legend OCR"
                )

        # A broken elective may contain an extra number
        # separated by whitespace instead of a slash.
        if re.search(
            r"\d{3,4}\s+\d{3,4}\s*/",
            text,
        ):
            issues.append(
                "Possible malformed elective OCR"
            )

        if extracted_codes:
            checked += 1

        if issues:
            findings.append({
                "day": cell["day"],
                "first_slot": cell["first_slot"],
                "last_slot": cell["last_slot"],
                "text": text,
                "codes": extracted_codes,
                "issues": list(dict.fromkeys(issues)),
                "image": cell.get("image"),
            })

    result = {
        "source": name,
        "legend_source": source,
        "legend_codes": sorted(legend),
        "legend_requires_review": uncertain,
        "cells_with_course_codes": checked,
        "cells_flagged": len(findings),
        "findings": findings,
        "note": (
            "Legend OCR may be incomplete. "
            "Flags are review suggestions, not proof of errors."
        ),
    }

    target = folder / "subject_validation_final.json"
    target.write_text(
        json.dumps(result, indent=2, ensure_ascii=False)
    )

    print(f"\n{'=' * 58}")
    print("CLASS:", name)
    print("Legend source:", source)
    print("Known candidate codes:", len(legend))
    print("Cells containing course codes:", checked)
    print("Cells flagged:", len(findings))

    for item in findings:
        print(
            f"\n{item['day']} "
            f"slots {item['first_slot']}-{item['last_slot']}"
        )
        print("  OCR:", item["text"])

        for issue in item["issues"]:
            print("  WARNING:", issue)

    print("\nSaved:", target)
    print("=" * 58)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    args = parser.parse_args()
    validate(args.name)


if __name__ == "__main__":
    main()
