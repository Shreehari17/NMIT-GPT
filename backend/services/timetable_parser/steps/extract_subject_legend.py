"""Extract subject codes from timetable legend and flag OCR inconsistencies.

Usage:
    python experiments/qwen_timetable/extract_subject_legend.py 7A.pdf
    python experiments/qwen_timetable/extract_subject_legend.py 6A.pdf

Diagnostic only: does not modify timetable JSON or backend.
"""
import argparse
import base64
import json
import re
from pathlib import Path

import pymupdf
from PIL import Image

from read_timetable_cells import MODEL, OLLAMA_URL, check_ollama, request_json

BASE = Path(__file__).resolve().parent

CODE_RE = re.compile(r"^22[A-Z]{2,5}\d{2,4}[A-Z]?$")
TIMETABLE_CODE_RE = re.compile(
    r"\b22[A-Z]{2,5}\d{2,4}[A-Z]?(?:/\d{2,4})*\b"
)

PROMPT = """
This image contains a college timetable subject-code legend.

Read ONLY course codes visible in the image.

Return JSON:
{
  "codes": ["22CS71"],
  "uncertain": false
}

Rules:
- Copy codes exactly.
- Include only codes visibly printed in the legend.
- Do not infer codes from semesters or course names.
- Do not invent missing codes.
- If a code is unreadable, omit it and set uncertain to true.
- Return valid JSON only.
"""


def save(path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False)
    )


def recognize(path):
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
            "num_predict": 600,
        },
    }

    response = request_json(
        f"{OLLAMA_URL}/api/chat",
        payload=payload,
        timeout=240,
    )

    text = response.get("message", {}).get("content", "")

    result = json.loads(text)

    if not isinstance(result, dict):
        raise ValueError("Expected JSON object")

    codes = result.get("codes", [])

    if not isinstance(codes, list):
        raise ValueError("Expected codes array")

    accepted = sorted({
        str(code).strip().upper()
        for code in codes
        if CODE_RE.fullmatch(str(code).strip().upper())
    })

    rejected = [
        str(code)
        for code in codes
        if not CODE_RE.fullmatch(str(code).strip().upper())
    ]

    return {
        "codes": accepted,
        "rejected_ocr_codes": rejected,
        "uncertain": result.get("uncertain") is not False,
    }


def expand_code(token):
    """Expand abbreviated elective codes without guessing new prefixes."""
    parts = token.split("/")
    first = parts[0]

    match = re.fullmatch(
        r"(22[A-Z]{2,5})(\d{2,4}[A-Z]?)",
        first,
    )

    if not match:
        return [first]

    prefix, number = match.groups()

    output = [first]

    for part in parts[1:]:
        part = part.strip()

        if CODE_RE.fullmatch(part):
            output.append(part)
        elif re.fullmatch(r"\d{2,4}[A-Z]?", part):
            output.append(prefix + part)

    return output


def compare_timetable(codes, timetable_path):
    data = json.loads(timetable_path.read_text())

    known = set(codes)
    findings = []
    seen = set()

    for cell in data.get("cells", []):
        text = str(cell.get("text") or "").strip()

        if not text:
            continue

        matches = TIMETABLE_CODE_RE.findall(text)

        for token in matches:
            for code in expand_code(token):
                if code not in known:
                    key = (
                        cell["day"],
                        cell["first_slot"],
                        cell["last_slot"],
                        code,
                    )

                    if key not in seen:
                        seen.add(key)
                        findings.append({
                            "day": cell["day"],
                            "first_slot": cell["first_slot"],
                            "last_slot": cell["last_slot"],
                            "detected_code": code,
                            "full_text": text,
                            "issue": "Code not confirmed by legend OCR",
                        })

        # Catch suspicious broken elective strings.
        if (
            "/" in text
            and re.search(r"\d\s+\d{3,4}/", text)
        ):
            findings.append({
                "day": cell["day"],
                "first_slot": cell["first_slot"],
                "last_slot": cell["last_slot"],
                "full_text": text,
                "issue": "Possible malformed elective code",
            })

    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    pdf_path = args.pdf
    name = pdf_path.stem

    folder = BASE / f"dynamic_grid_{name}" / "page_1"
    segmentation_path = folder / "segmentation.json"
    schedule_path = folder / "schedule_region.json"

    for path in [pdf_path, segmentation_path, schedule_path]:
        if not path.exists():
            raise FileNotFoundError(path)

    segmentation = json.loads(segmentation_path.read_text())
    schedule = json.loads(schedule_path.read_text())

    x, y, width, height = segmentation["candidate_bbox"]

    legend_y = segmentation["legend_header_band"][0]

    right = x + schedule["schedule_width"]
    bottom = y + height

    check_ollama()

    with pymupdf.open(pdf_path) as pdf:
        pix = pdf[0].get_pixmap(
            matrix=pymupdf.Matrix(3, 3),
            colorspace=pymupdf.csRGB,
            alpha=False,
        )

        image = Image.frombytes(
            "RGB",
            (pix.width, pix.height),
            pix.samples,
        )

    # Crop the subject legend area using detected document geometry.
    box = (
        max(0, x),
        max(0, legend_y - 5),
        min(image.width, right),
        min(image.height, bottom),
    )

    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("Invalid subject legend crop")

    crop = image.crop(box)

    crop_path = folder / "subject_legend_crop.png"
    crop.save(crop_path)

    print("Reading subject legend...", flush=True)

    result = recognize(crop_path)

    dynamic_ocr = folder / "dynamic_ocr.json"
    findings = []

    if dynamic_ocr.exists():
        findings = compare_timetable(
            result["codes"],
            dynamic_ocr,
        )

    output = {
        "source_pdf": pdf_path.name,
        "codes": result["codes"],
        "legend_ocr_uncertain": result["uncertain"],
        "rejected_ocr_codes": result["rejected_ocr_codes"],
        "findings": findings,
        "note": (
            "Unmatched codes may indicate incomplete legend OCR. "
            "Do not automatically change timetable values."
        ),
    }

    target = folder / "subject_legend_review.json"
    save(target, output)

    print("\n" + "=" * 55)
    print("PDF:", pdf_path.name)
    print("Legend codes:", result["codes"])
    print("OCR uncertain:", result["uncertain"])
    print("Codes requiring review:", len(findings))

    for finding in findings:
        print(
            f"  {finding['day']} "
            f"slots {finding['first_slot']}-{finding['last_slot']}: "
            f"{finding['issue']} — {finding['full_text']}"
        )

    print("\nLegend crop:", crop_path)
    print("Saved:", target)
    print("=" * 55)


if __name__ == "__main__":
    main()
