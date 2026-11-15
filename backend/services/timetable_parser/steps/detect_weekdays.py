"""Detect weekday rows dynamically using OpenCV and local Ollama.

Usage:
    python experiments/qwen_timetable/detect_weekdays.py 7A
    python experiments/qwen_timetable/detect_weekdays.py 6A

Requires schedule_only.png from isolate_schedule.py.
Does not modify the existing extraction pipeline.
"""

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from read_timetable_cells import MODEL, OLLAMA_URL, request_json

BASE = Path(__file__).resolve().parent

WEEKDAYS = {
    name.upper(): name
    for name in (
        "Monday", "Tuesday", "Wednesday",
        "Thursday", "Friday", "Saturday", "Sunday"
    )
}


def clusters(values, gap=4):
    values = list(map(int, values))
    if not values:
        return []

    groups = [[values[0]]]

    for value in values[1:]:
        if value - groups[-1][-1] > gap:
            groups.append([])
        groups[-1].append(value)

    return [int(np.median(group)) for group in groups]


def detect_grid(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape

    ink = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31, 12
    )

    # Identify continuous vertical lines.
    vertical = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (1, max(20, height // 8))
        )
    )

    coverage = (
        vertical[int(height * 0.12):int(height * 0.92)] > 0
    ).sum(axis=0)

    possible = np.flatnonzero(
        (coverage > height * 0.48)
        & (np.arange(width) > width * 0.04)
        & (np.arange(width) < width * 0.28)
    )

    separators = clusters(possible)

    if not separators:
        raise ValueError(
            "Day-column separator not detected."
        )

    # First substantial inner vertical line separates
    # weekday labels from timetable periods.
    day_right = separators[0]

    horizontal = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (max(18, int(day_right * 0.45)), 1)
        )
    )

    left = 5
    right = day_right - 5

    if right <= left + 20:
        raise ValueError("Day column is too narrow.")

    row_coverage = (
        horizontal[:, left:right] > 0
    ).mean(axis=1)

    boundaries = clusters(
        np.flatnonzero(row_coverage > 0.66)
    )

    if not boundaries:
        raise ValueError("No horizontal boundaries found.")

    if boundaries[-1] < height - 5:
        boundaries.append(height - 1)

    regions = [
        (top, bottom)
        for top, bottom in zip(
            boundaries, boundaries[1:]
        )
        if bottom - top >= 17
    ]

    if len(regions) < 3:
        raise ValueError(
            "Not enough row candidates found."
        )

    return day_right, boundaries, regions


def read_label(image_path):
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
            "content": (
                "Read ONLY the visible text in this "
                "single timetable first-column cell. "
                "Do not guess a weekday if it isn't visible. "
                "Return ONLY JSON with fields "
                "text and uncertain. "
                "Example: "
                '{"text":"MONDAY","uncertain":false}'
            ),
            "images": [encoded]
        }],
        "options": {
            "temperature": 0,
            "num_ctx": 4096,
            "num_predict": 90
        }
    }

    response = request_json(
        f"{OLLAMA_URL}/api/chat",
        payload=payload,
        timeout=180
    )

    raw = response.get(
        "message", {}
    ).get("content", "")

    try:
        result = json.loads(raw)

        return (
            str(result.get("text") or ""),
            result.get("uncertain") is not False
        )
    except (ValueError, TypeError, AttributeError):
        return str(raw), True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    args = parser.parse_args()

    folder = (
        BASE
        / f"dynamic_grid_{args.name}"
        / "page_1"
    )

    source = folder / "schedule_only.png"
    image = cv2.imread(str(source))

    if image is None:
        raise FileNotFoundError(source)

    day_right, boundaries, regions = detect_grid(image)

    crop_dir = folder / "weekday_crops"
    crop_dir.mkdir(exist_ok=True)

    cache_path = crop_dir / "ocr_cache.json"

    try:
        cache = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        cache = {}

    days = []
    other_rows = []
    header = None
    overlay = image.copy()

    print(
        f"\nDay-column boundary: x={day_right}"
    )
    print(
        f"Detected {len(regions)} possible rows\n",
        flush=True
    )

    for index, (top, bottom) in enumerate(regions, 1):
        crop = image[
            top + 3:bottom - 3,
            3:day_right - 3
        ]

        if crop.size == 0:
            continue

        rgb = cv2.cvtColor(
            crop, cv2.COLOR_BGR2RGB
        )

        pil = ImageOps.expand(
            Image.fromarray(rgb),
            border=18,
            fill="white"
        )

        pil = pil.resize(
            (pil.width * 3, pil.height * 3),
            Image.Resampling.LANCZOS
        )

        crop_path = crop_dir / f"row_{index:02d}.png"
        pil.save(crop_path)

        digest = hashlib.sha256(
            crop_path.read_bytes()
        ).hexdigest()

        key = f"{MODEL}:{digest}"

        if key in cache:
            recognized, uncertain = cache[key]
        else:
            try:
                recognized, uncertain = read_label(
                    crop_path
                )

                cache[key] = [recognized, uncertain]
                cache_path.write_text(
                    json.dumps(cache, indent=2)
                )
            except Exception as exc:
                recognized, uncertain = "", True
                print(
                    f"OCR failed on row {index}: {exc}"
                )

        cleaned = re.sub(
            r"[^A-Z]", "", recognized.upper()
        )

        if cleaned in WEEKDAYS and not uncertain and header is not None:
            day = WEEKDAYS[cleaned]

            days.append({
                "day": day,
                "top": top,
                "bottom": bottom,
                "raw": recognized,
                "image": crop_path.name
            })

            cv2.rectangle(
                overlay,
                (2, top),
                (day_right, bottom),
                (0, 180, 0),
                2
            )

            print(
                f"{day:<12} y={top}-{bottom}",
                flush=True
            )

        elif cleaned in {
            "DAYTIME",
            "DAYTIMES",
            "DAYTIMEPERIOD"
        }:
            header = {
                "top": top,
                "bottom": bottom,
                "raw": recognized
            }

            cv2.rectangle(
                overlay,
                (2, top),
                (day_right, bottom),
                (255, 150, 0),
                2
            )

            print(
                f"HEADER       y={top}-{bottom}",
                flush=True
            )

        else:
            other_rows.append({
                "top": top,
                "bottom": bottom,
                "raw": recognized,
                "uncertain": uncertain
            })

            print(
                f"Other row    y={top}-{bottom}: "
                f"{recognized!r}",
                flush=True
            )

    names = [row["day"] for row in days]

    warnings = []

    if not days:
        warnings.append("No weekdays recognized")

    if len(set(names)) != len(names):
        warnings.append("Duplicate weekday labels")

    if header is None:
        warnings.append("DAY/TIME header not confirmed")

    result = {
        "source": str(source),
        "day_column_right": day_right,
        "row_boundaries": boundaries,
        "header": header,
        "days": days,
        "other_rows": other_rows,
        "warnings": warnings,
        "needs_review": bool(warnings)
    }

    output = folder / "weekday_rows.json"
    output.write_text(
        json.dumps(result, indent=2)
    )

    cv2.imwrite(
        str(folder / "weekday_overlay.png"),
        overlay
    )

    print("\n" + "=" * 45)
    print(f"Detected weekdays: {len(days)}")
    print("Names:", names)
    print("Needs review:", bool(warnings))
    print("Saved:", output)
    print("=" * 45)


if __name__ == "__main__":
    main()
