"""Detect class/section from the PDF itself, not its filename.

Usage:
    python experiments/qwen_timetable/detect_class.py 7A.pdf
    python experiments/qwen_timetable/detect_class.py 6A.pdf

Diagnostic only. Does not modify backend or existing OCR.
"""

import argparse
import base64
import json
import re
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

from read_timetable_cells import (
    MODEL,
    OLLAMA_URL,
    check_ollama,
    request_json,
)

BASE = Path(__file__).resolve().parent

PROMPT = """
Read the document heading of this college timetable.

Find the class, semester and section, if explicitly printed.

Examples of possible formats:
- VII A
- 7th Semester Section A
- Semester 6, Section A
- VI-A

Rules:
- Do not use the filename.
- Do not infer the class from subject codes.
- Do not guess an absent section.
- Copy supporting text exactly as visible.
- If information is missing, use null.
- Return only JSON.

Expected structure:
{
  "semester": null,
  "section": null,
  "evidence": "",
  "uncertain": true
}
"""


def ask_qwen(image_path):
    encoded = base64.b64encode(
        image_path.read_bytes()
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
            "num_ctx": 4096,
            "num_predict": 220,
        },
    }

    response = request_json(
        f"{OLLAMA_URL}/api/chat",
        payload=payload,
        timeout=180,
    )

    content = response.get(
        "message", {}
    ).get("content", "")

    result = json.loads(content)

    if not isinstance(result, dict):
        raise ValueError("Expected JSON object")

    return result


def normalize_class(result):
    semester = result.get("semester")
    section = result.get("section")

    if semester is None or section is None:
        return None

    semester_text = str(semester).strip().upper()
    section_text = str(section).strip().upper()

    roman = {
        "I": 1,
        "II": 2,
        "III": 3,
        "IV": 4,
        "V": 5,
        "VI": 6,
        "VII": 7,
        "VIII": 8,
    }

    if semester_text in roman:
        number = roman[semester_text]
    elif re.fullmatch(r"[1-9][0-9]?", semester_text):
        number = int(semester_text)
    else:
        return None

    if not re.fullmatch(r"[A-Z]", section_text):
        return None

    return f"{number}{section_text}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    pdf_path = args.pdf

    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    check_ollama()

    output_dir = BASE / f"class_detection_{pdf_path.stem}"
    output_dir.mkdir(parents=True, exist_ok=True)

    with pymupdf.open(pdf_path) as pdf:
        if not pdf:
            raise ValueError("Empty PDF")

        page = pdf[0]

        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(3, 3),
            colorspace=pymupdf.csRGB,
            alpha=False,
        )

        image = Image.frombytes(
            "RGB",
            (pix.width, pix.height),
            pix.samples,
        )

    # Inspect the upper document region, where class
    # metadata is commonly printed. This is a candidate
    # region, not a guaranteed layout-independent location.
    heading = image.crop((
        0,
        0,
        image.width,
        int(image.height * 0.40),
    ))

    heading = ImageOps.expand(
        heading,
        border=15,
        fill="white",
    )

    image_path = output_dir / "heading.png"
    heading.save(image_path)

    result = ask_qwen(image_path)
    class_name = normalize_class(result)

    output = {
        "source_pdf": pdf_path.name,
        "detected_class": class_name,
        "semester": result.get("semester"),
        "section": result.get("section"),
        "evidence": result.get("evidence", ""),
        "model_uncertain": result.get("uncertain", True),
        "needs_review": (
            class_name is None
            or result.get("uncertain") is not False
        ),
        "image": str(image_path),
    }

    target = output_dir / "class_detection.json"

    target.write_text(
        json.dumps(output, indent=2, ensure_ascii=False)
    )

    print("\n" + "=" * 55)
    print("PDF:", pdf_path.name)
    print("Detected class:", class_name or "NOT CONFIRMED")
    print("Semester:", output["semester"])
    print("Section:", output["section"])
    print("Evidence:", output["evidence"])
    print("Needs review:", output["needs_review"])
    print("Saved:", target)
    print("=" * 55)

    print(
        "\nClass detection is provisional until "
        "the evidence is checked against the PDF."
    )


if __name__ == "__main__":
    main()
