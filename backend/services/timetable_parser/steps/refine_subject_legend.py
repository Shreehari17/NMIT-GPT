"""Improve subject legend OCR using overlapping image crops.

Usage:
    python experiments/qwen_timetable/refine_subject_legend.py 6A
    python experiments/qwen_timetable/refine_subject_legend.py 7A

Diagnostic only. Does not overwrite original OCR results.
"""

import argparse
import base64
import json
import re
from pathlib import Path

from PIL import Image, ImageOps
from read_timetable_cells import (
    MODEL,
    check_ollama,
    request_json,
    OLLAMA_URL,
)

BASE = Path(__file__).resolve().parent

CODE_PATTERN = re.compile(
    r"22[A-Z]{2,5}\d{2,4}[A-Z]?"
)

PROMPT = """
You are reading a CROPPED section of a college
timetable SUBJECT CODE legend.

Extract only complete subject codes visibly printed.

IMPORTANT:
- Preserve ALL letters between 22 and the numbers.
- 22CS64, 22CSG64, and 22CSL64 are different codes.
- Do not remove G, L, E, O, or any other letters.
- Do not infer codes from subject names.
- Do not complete cropped or partly visible codes.
- If a code is unclear, omit it and mark uncertain.
- Do not use information from other images.

Return only valid JSON:

{
  "codes": [],
  "uncertain": false
}
"""


def read_codes(path):
    encoded = base64.b64encode(
        path.read_bytes()
    ).decode("ascii")

    payload = {
        "model": MODEL,
        "stream": False,
        "format": "json",
        "think": False,
        "messages": [{
            "role": "user",
            "content": PROMPT,
            "images": [encoded],
        }],
        "options": {
            "temperature": 0,
            "num_ctx": 8192,
            "num_predict": 500,
        },
    }

    response = request_json(
        f"{OLLAMA_URL}/api/chat",
        payload=payload,
        timeout=240,
    )

    content = response["message"]["content"]
    data = json.loads(content)

    if not isinstance(data, dict):
        raise ValueError("Unexpected OCR response")

    raw_codes = data.get("codes", [])

    if not isinstance(raw_codes, list):
        raise ValueError("Expected a list of codes")

    accepted = []
    rejected = []

    for raw in raw_codes:
        code = str(raw).strip().upper()

        if CODE_PATTERN.fullmatch(code):
            accepted.append(code)
        else:
            rejected.append(code)

    return {
        "codes": sorted(set(accepted)),
        "rejected": rejected,
        "uncertain": data.get("uncertain") is not False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    args = parser.parse_args()

    folder = (
        BASE
        / f"dynamic_grid_{args.name}"
        / "page_1"
    )

    source = folder / "subject_legend_crop.png"

    if not source.exists():
        raise FileNotFoundError(
            f"Missing {source}. Run extract_subject_legend.py first."
        )

    original_report = folder / "subject_legend_review.json"

    original = json.loads(original_report.read_text())
    original_codes = set(original.get("codes", []))

    check_ollama()

    image = Image.open(source).convert("RGB")
    width, height = image.size

    # Overlap sections to avoid losing codes at crop boundaries.
    sections = [
        (0.00, 0.45),
        (0.30, 0.75),
        (0.60, 1.00),
    ]

    reports = []
    collected = set()

    for index, (start, end) in enumerate(sections, 1):
        y0 = int(height * start)
        y1 = int(height * end)

        crop = image.crop((0, y0, width, y1))

        crop = ImageOps.expand(
            crop,
            border=12,
            fill="white",
        )

        path = folder / f"legend_section_{index}.png"
        crop.save(path)

        print(
            f"\nReading legend section {index}/3",
            flush=True,
        )

        try:
            result = read_codes(path)
        except Exception as exc:
            result = {
                "codes": [],
                "rejected": [],
                "uncertain": True,
                "error": str(exc),
            }

        collected.update(result["codes"])

        reports.append({
            "section": index,
            "image": path.name,
            **result,
        })

        print(
            "Codes:", result["codes"],
            flush=True,
        )

        if result.get("error"):
            print("Error:", result["error"], flush=True)

    combined = original_codes | collected

    output = {
        "source_pdf": f"{args.name}.pdf",
        "original_codes": sorted(original_codes),
        "section_codes": sorted(collected),
        "candidate_codes": sorted(combined),
        "new_candidates": sorted(
            collected - original_codes
        ),
        "sections": reports,
        "requires_review": True,
        "note": (
            "Candidate codes require comparison with the "
            "visible subject legend. Union is not proof."
        ),
    }

    target = folder / "subject_legend_refined.json"

    target.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        )
    )

    print("\n" + "=" * 55)
    print("CLASS:", args.name)
    print("Original codes:", len(original_codes))
    print("Section OCR codes:", len(collected))
    print("Combined candidates:", len(combined))

    print("\nNew code candidates:")
    for code in output["new_candidates"]:
        print(" ", code)

    print("\nSaved:", target)
    print("Review the section images before accepting codes.")
    print("=" * 55)


if __name__ == "__main__":
    main()
