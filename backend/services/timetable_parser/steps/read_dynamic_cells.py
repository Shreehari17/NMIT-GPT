"""OCR dynamically detected timetable cells.

Usage:
  python experiments/qwen_timetable/read_dynamic_cells.py 7A --limit 5
  python experiments/qwen_timetable/read_dynamic_cells.py 7A
  python experiments/qwen_timetable/read_dynamic_cells.py 6A

Uses dynamic geometry, not hardcoded days or period counts.
Does not modify backend, database, or original OCR outputs.
"""

import argparse
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path

import cv2
import numpy as np

from read_timetable_cells import check_ollama, read_with_retries, MODEL, PROMPT

BASE = Path(__file__).resolve().parent

# Stable across upload workspaces, but isolated to the current OS user.
# Include the OCR prompt in the key so prompt/model changes invalidate results.
CACHE_VERSION = "cell-ocr-v1"


def persistent_cache_key(crop_bytes):
    prefix = f"{CACHE_VERSION}\n{MODEL}\n{PROMPT}\n".encode("utf-8")
    return hashlib.sha256(prefix + crop_bytes).hexdigest()


def read_persistent_cache(cache_dir, key):
    if cache_dir is None:
        return None
    path = cache_dir / f"{key}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (isinstance(data, dict) and isinstance(data.get("text"), str)
                and isinstance(data.get("uncertain"), bool)
                and isinstance(data.get("reason", ""), str)):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return None


def write_persistent_cache(cache_dir, key, result):
    if cache_dir is None:
        return
    if not (isinstance(result, dict) and isinstance(result.get("text"), str)
            and isinstance(result.get("uncertain"), bool)):
        return
    payload = json.dumps(result, ensure_ascii=False)
    # Atomic replacement; concurrent requests cannot leave truncated JSON.
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".ocr-", dir=cache_dir)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temporary, cache_dir / f"{key}.json")
    except OSError as exc:
        print(f"  Persistent OCR cache unavailable: {exc}", flush=True)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def get_persistent_cache_directory():
    raw = os.environ.get("NMIT_TIMETABLE_OCR_CACHE_DIR")
    if not raw:
        return None
    cache_dir = Path(raw).expanduser()
    try:
        cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Never put course OCR into a world-readable shared folder.
        if cache_dir.stat().st_mode & 0o077:
            print("Persistent cache disabled: directory permissions too open", flush=True)
            return None
    except OSError as exc:
        print(f"Persistent cache disabled: {exc}", flush=True)
        return None
    return cache_dir


def save_json(path, data):
    temp = path.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False)
    )
    temp.replace(path)


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def horizontal_map(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    ink = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        12,
    )

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(18, image.shape[1] // 75), 1),
    )

    return cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        kernel,
    )


def boundary_exists(horizontal, y, x0, x1):
    """Check whether a horizontal border crosses this cell."""
    height, width = horizontal.shape

    x0 = max(0, x0 + 7)
    x1 = min(width, x1 - 7)

    y0 = max(0, y - 3)
    y1 = min(height, y + 4)

    if x1 <= x0 or y1 <= y0:
        return False

    region = horizontal[y0:y1, x0:x1]

    coverage = (region > 0).any(axis=0).mean()

    return bool(coverage >= 0.65)


def mark_vertical_merges(cells, image):
    """Flag cells whose top/bottom borders are absent.

    A missing border suggests a vertically merged region.
    We flag it for review instead of treating fragmented
    letters as independent classes.
    """
    horizontal = horizontal_map(image)

    indexed = {}

    for cell in cells:
        indexed.setdefault(cell["day"], []).append(cell)

    days = list(indexed)

    for day_index, day in enumerate(days):
        for cell in indexed[day]:
            x0 = int(cell["x0"])
            x1 = int(cell["x1"])
            top = int(cell["y0"])
            bottom = int(cell["y1"])

            from_previous = False
            into_next = False

            if day_index > 0:
                from_previous = not boundary_exists(
                    horizontal, top, x0, x1
                )

            if day_index < len(days) - 1:
                into_next = not boundary_exists(
                    horizontal, bottom, x0, x1
                )

            cell["continues_from_previous_day"] = (
                from_previous
            )
            cell["continues_into_next_day"] = into_next

            cell["vertical_merge_review"] = (
                from_previous or into_next
            )

    return cells


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    folder = (
        BASE / f"dynamic_grid_{args.name}" / "page_1"
    )

    geometry_path = folder / "dynamic_geometry.json"
    csv_path = folder / "dynamic_cells.csv"
    image_path = folder / "schedule_only.png"

    for path in (geometry_path, csv_path, image_path):
        if not path.exists():
            raise FileNotFoundError(path)

    geometry = load_json(geometry_path, {})

    with csv_path.open(newline="") as file:
        cells = list(csv.DictReader(file))

    image = cv2.imread(str(image_path))

    if image is None:
        raise ValueError("Could not read schedule image")

    if not cells:
        raise ValueError("No dynamic cells detected")

    cells = mark_vertical_merges(cells, image)

    # Validate detected geometry before model inference.
    day_names = [
        item["day"] for item in geometry["days"]
    ]

    period_count = geometry["period_count"]

    for cell in cells:
        first = int(cell["first_slot"])
        last = int(cell["last_slot"])

        if (
            cell["day"] not in day_names
            or first < 1
            or last > period_count
            or first > last
        ):
            raise ValueError(
                f"Invalid dynamic cell: {cell}"
            )

    check_ollama()

    cache_path = folder / "dynamic_ocr_cache.json"
    output_path = folder / "dynamic_ocr.json"
    review_path = folder / "dynamic_ocr_review.json"

    cache = load_json(cache_path, {})
    persistent_dir = get_persistent_cache_directory()
    cache_hits = 0
    model_calls = 0

    selected = (
        cells[:args.limit]
        if args.limit is not None
        else cells
    )

    records = []

    print(
        f"\nDays: {len(day_names)}"
        f"\nPeriods: {period_count}"
        f"\nProcessing: {len(selected)}/{len(cells)} cells\n",
        flush=True,
    )

    for index, cell in enumerate(selected, 1):
        day = cell["day"]
        first = int(cell["first_slot"])
        last = int(cell["last_slot"])

        crop_path = (
            folder / "dynamic_crops" / cell["image"]
        )

        if not crop_path.exists():
            raise FileNotFoundError(crop_path)

        print(
            f"[{index}/{len(selected)}] "
            f"{day} slots {first}-{last}",
            flush=True,
        )

        if cell["vertical_merge_review"]:
            result = {
                "text": "",
                "uncertain": True,
                "reason": (
                    "Possible vertically merged region. "
                    "Read the complete merged cell separately."
                ),
            }

            status = "vertical_merge_review"

            print("  Vertical merge: review", flush=True)

        else:
            digest = hashlib.sha256(
                crop_path.read_bytes()
            ).hexdigest()

            cache_key = (
                f"qwen2.5vl:3b:{digest}"
            )

            stable_key = persistent_cache_key(crop_path.read_bytes())
            result = read_persistent_cache(persistent_dir, stable_key)
            if result is None:
                result = cache.get(cache_key)
            if result is not None:
                cache_hits += 1
                print(f"  Cached: {result.get('text', '')!r}", flush=True)
            else:
                model_calls += 1
                result = read_with_retries(crop_path)
                print(f"  OCR: {result.get('text', '')!r}", flush=True)

            cache[cache_key] = result
            save_json(cache_path, cache)
            write_persistent_cache(persistent_dir, stable_key, result)

            status = (
                "needs_review"
                if result.get("uncertain")
                or not result.get("text")
                else "recognized"
            )

        records.append({
            "day": day,
            "first_slot": first,
            "last_slot": last,
            "text": result.get("text", ""),
            "status": status,
            "uncertain": result.get("uncertain", True),
            "reason": result.get("reason", ""),
            "image": cell["image"],
            "continues_from_previous_day": (
                cell["continues_from_previous_day"]
            ),
            "continues_into_next_day": (
                cell["continues_into_next_day"]
            ),
        })

        output = {
            "source": args.name,
            "day_names": day_names,
            "period_count": period_count,
            "processed_cells": len(records),
            "total_cells": len(cells),
            "complete": len(records) == len(cells),
            "cells": records,
        }

        save_json(output_path, output)

        save_json(
            review_path,
            [
                record for record in records
                if record["status"] != "recognized"
            ],
        )

    print(f"OCR cache hits: {cache_hits}; model calls: {model_calls}", flush=True)
    print("\nFinished!", flush=True)
    print("Output:", output_path)
    print("Review:", review_path)
    print(
        "\nNote: OCR text and vertical merge flags "
        "still need source-PDF validation."
    )


if __name__ == "__main__":
    main()
