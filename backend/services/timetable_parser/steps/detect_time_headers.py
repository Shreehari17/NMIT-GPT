"""Detect timetable time headers from PDF using existing grid geometry.

Usage:
  python experiments/qwen_timetable/detect_time_headers.py 7A --limit 3
  python experiments/qwen_timetable/detect_time_headers.py 7A
  python experiments/qwen_timetable/detect_time_headers.py 6A

Diagnostic only: does not change original OCR JSON or backend.
"""

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

import pymupdf
from PIL import Image, ImageEnhance, ImageOps

from read_timetable_cells import MODEL, OLLAMA_URL, request_json

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent.parent


def save_json(path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False)
    )


def normalize_time(text):
    text = str(text or "").strip()

    text = (
        text.replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace(".", ":")
    )

    matches = re.findall(
        r"(\d{1,2})\s*:\s*(\d{2})\s*-\s*"
        r"(\d{1,2})\s*:\s*(\d{2})",
        text,
    )

    if len(matches) != 1:
        return None

    h1, m1, h2, m2 = map(int, matches[0])

    if not (
        1 <= h1 <= 23
        and 1 <= h2 <= 23
        and 0 <= m1 < 60
        and 0 <= m2 < 60
    ):
        return None

    if h1 == h2 and m1 == m2:
        return None

    return f"{h1:02d}:{m1:02d}-{h2:02d}:{m2:02d}"


def recognize_header(image_path):
    image_data = base64.b64encode(
        image_path.read_bytes()
    ).decode("ascii")

    payload = {
        "model": MODEL,
        "stream": False,
        "format": "json",
        "think": False,
        "messages": [{
            "role": "user",
            "content": (
                "Read ONLY the time range printed in this "
                "college timetable header cell. "
                "Preserve the exact hour and minute numbers. "
                "Do not invent missing times. "
                "Return ONLY a JSON object like "
                '{"time_range":"9:00-9:55",'
                '"uncertain":false}. '
                "If unreadable, set time_range to an empty "
                "string and uncertain to true."
            ),
            "images": [image_data],
        }],
        "options": {
            "temperature": 0,
            "num_ctx": 4096,
            "num_predict": 120,
        },
    }

    response = request_json(
        f"{OLLAMA_URL}/api/chat",
        payload=payload,
        timeout=180,
    )

    content = (
        response.get("message", {})
        .get("content", "")
        .strip()
    )

    try:
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("Response is not an object")

        return {
            "raw": str(result.get("time_range") or ""),
            "uncertain": result.get("uncertain") is not False,
        }

    except (ValueError, json.JSONDecodeError):
        return {
            "raw": content,
            "uncertain": True,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    folder = BASE / f"cells_{args.name}"
    geometry_path = folder / "geometry.json"
    pdf_path = ROOT / f"{args.name}.pdf"

    if not geometry_path.exists():
        raise FileNotFoundError(geometry_path)

    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    geometry = json.loads(geometry_path.read_text())
    columns = geometry["columns"]
    rows = geometry["rows"]

    # First column contains weekday labels.
    # The remaining columns are time periods.
    period_count = len(columns) - 2

    if period_count < 1:
        raise ValueError("No time columns detected")

    with pymupdf.open(pdf_path) as pdf:
        pix = pdf[0].get_pixmap(
            matrix=pymupdf.Matrix(3, 3),
            alpha=False,
        )

        image = Image.frombytes(
            "RGB",
            (pix.width, pix.height),
            pix.samples,
        )

    header_dir = folder / "header_crops"
    header_dir.mkdir(parents=True, exist_ok=True)

    output_path = folder / "time_headers.json"
    cache_path = header_dir / "header_ocr_cache.json"

    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError):
        cache = {}

    results = []
    count = period_count

    if args.limit is not None:
        count = min(period_count, max(0, args.limit))

    print(f"\nDetected {period_count} header columns")
    print(f"Processing {count} headers\n", flush=True)

    for i in range(1, count + 1):
        x0 = columns[i] + 3
        x1 = columns[i + 1] - 3
        y0 = rows[0] + 3
        y1 = rows[1] - 3

        if x1 <= x0 or y1 <= y0:
            raise ValueError(
                f"Invalid crop coordinates at slot {i}"
            )

        crop = image.crop((x0, y0, x1, y1))

        # Enlarge tiny printed time labels.
        crop = ImageOps.expand(
            crop,
            border=16,
            fill="white",
        )
        crop = crop.resize(
            (crop.width * 3, crop.height * 3),
            Image.Resampling.LANCZOS,
        )
        crop = ImageEnhance.Contrast(crop).enhance(1.5)

        image_path = header_dir / f"slot_{i:02d}.png"
        crop.save(image_path)

        digest = hashlib.sha256(
            image_path.read_bytes()
        ).hexdigest()

        key = f"{MODEL}:{digest}"

        if key in cache:
            recognized = cache[key]
            source = "cached"
        else:
            try:
                recognized = recognize_header(image_path)
                cache[key] = recognized
                save_json(cache_path, cache)
                source = "ollama"
            except Exception as exc:
                recognized = {
                    "raw": "",
                    "uncertain": True,
                    "error": str(exc),
                }
                source = "error"

        normalized = normalize_time(recognized["raw"])

        result = {
            "slot": i,
            "raw": recognized["raw"],
            "time_range": normalized,
            "needs_review": (
                normalized is None
                or recognized.get("uncertain", True)
            ),
            "image": str(image_path),
            "source": source,
        }

        if recognized.get("error"):
            result["error"] = recognized["error"]

        results.append(result)

        print(
            f"Slot {i:02d}: "
            f"{normalized or 'UNREADABLE'} "
            f"| raw={recognized['raw']!r} "
            f"| review={result['needs_review']}",
            flush=True,
        )

    save_json(output_path, {
        "source_pdf": pdf_path.name,
        "detected_period_count": period_count,
        "processed_period_count": len(results),
        "complete": len(results) == period_count,
        "headers": results,
    })

    print(f"\nSaved: {output_path}")
    print(f"Header images: {header_dir}")
    print(
        "\nNote: Times are transcribed, not yet "
        "resolved into a full-day chronological schedule."
    )


if __name__ == "__main__":
    main()
