"""Build dynamic timetable cell geometry from detected weekday rows.

Uses:
  dynamic_grid_<name>/page_1/schedule_only.png
  dynamic_grid_<name>/page_1/weekday_rows.json

Outputs:
  dynamic_geometry.json
  dynamic_cells.csv
  dynamic_cells_preview.png
  dynamic_crops/

Does not use fixed day counts, period counts, subject codes,
BREAK positions, or LUNCH positions.
Does not modify existing extracted timetables.
"""

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent


def cluster(values, tolerance=5):
    values = sorted(int(x) for x in values)
    if not values:
        return []

    groups = [[values[0]]]

    for value in values[1:]:
        if value - groups[-1][-1] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])

    return [int(np.median(group)) for group in groups]


def vertical_lines(gray):
    height, width = gray.shape

    ink = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31, 12
    )

    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (1, max(9, height // 35))
    )

    vertical = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        kernel
    )

    return vertical


def find_columns(vertical, header, image_width, day_right):
    top = header["top"]
    bottom = header["bottom"]

    # Avoid horizontal rules at the edges of the header.
    margin = max(3, int((bottom - top) * 0.12))
    region = vertical[top + margin:bottom - margin]

    if region.size == 0:
        raise ValueError("Header region is empty")

    coverage = (region > 0).mean(axis=0)

    candidates = cluster(
        np.flatnonzero(coverage >= 0.65),
        tolerance=5
    )

    # Ensure known outer and day-column boundaries are present.
    boundaries = [0, day_right, image_width - 1]

    for x in candidates:
        if x <= 3 or x >= image_width - 4:
            continue
        if all(abs(x - b) > 6 for b in boundaries):
            boundaries.append(x)

    boundaries = sorted(boundaries)

    # Remove adjacent duplicates caused by thick lines.
    cleaned = []
    for x in boundaries:
        if not cleaned or x - cleaned[-1] > 6:
            cleaned.append(x)

    # Day-column boundary must remain the second boundary.
    if len(cleaned) < 4:
        raise ValueError(
            f"Insufficient column boundaries: {cleaned}"
        )

    if abs(cleaned[1] - day_right) > 8:
        raise ValueError(
            "Detected columns disagree with day-column boundary"
        )

    widths = np.diff(cleaned)

    if min(widths) < 12:
        raise ValueError(
            f"Suspiciously narrow column: {cleaned}"
        )

    return cleaned


def border_present(vertical, x, top, bottom):
    height, width = vertical.shape

    row_height = bottom - top
    margin = max(5, int(row_height * 0.18))

    y0 = max(0, top + margin)
    y1 = min(height, bottom - margin)

    if y1 <= y0:
        return False

    x0 = max(0, x - 3)
    x1 = min(width, x + 4)

    pixels = vertical[y0:y1, x0:x1]

    if pixels.size == 0:
        return False

    coverage = (pixels > 0).any(axis=1).mean()

    return coverage >= 0.52


def extract_cells(image, vertical, boundaries, weekdays, output_dir):
    cells = []
    crops_dir = output_dir / "dynamic_crops"
    crops_dir.mkdir(exist_ok=True)

    preview = image.copy()
    period_count = len(boundaries) - 2

    for day_info in weekdays:
        day = day_info["day"]
        top = int(day_info["top"])
        bottom = int(day_info["bottom"])

        if top >= bottom:
            raise ValueError(f"Invalid row: {day}")

        start = 1

        while start <= period_count:
            end = start

            # If the vertical border between two periods is absent,
            # those periods belong to the same horizontally merged cell.
            while end < period_count:
                separator_x = boundaries[end + 1]

                if border_present(
                    vertical,
                    separator_x,
                    top,
                    bottom
                ):
                    break

                end += 1

            x0 = boundaries[start]
            x1 = boundaries[end + 1]

            pad = 3

            crop = image[
                top + pad:bottom - pad,
                x0 + pad:x1 - pad
            ]

            filename = (
                f"{day}_slots_{start:02d}-{end:02d}.png"
            )

            if crop.size:
                cv2.imwrite(
                    str(crops_dir / filename),
                    crop
                )

            cells.append({
                "day": day,
                "first_slot": start,
                "last_slot": end,
                "x0": x0,
                "y0": top,
                "x1": x1,
                "y1": bottom,
                "image": filename
            })

            cv2.rectangle(
                preview,
                (x0, top),
                (x1, bottom),
                (0, 180, 0),
                2
            )

            start = end + 1

    return cells, preview


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    args = parser.parse_args()

    folder = (
        BASE / f"dynamic_grid_{args.name}" / "page_1"
    )

    image_path = folder / "schedule_only.png"
    weekdays_path = folder / "weekday_rows.json"

    image = cv2.imread(str(image_path))

    if image is None:
        raise FileNotFoundError(image_path)

    data = json.loads(weekdays_path.read_text())

    if data.get("needs_review"):
        raise ValueError(
            "Weekday detection requires review."
        )

    if not data.get("header"):
        raise ValueError("DAY/TIME header not found.")

    weekdays = data["days"]

    if not weekdays:
        raise ValueError("No weekday rows detected.")

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    vertical = vertical_lines(gray)

    boundaries = find_columns(
        vertical,
        data["header"],
        image.shape[1],
        data["day_column_right"]
    )

    cells, preview = extract_cells(
        image,
        vertical,
        boundaries,
        weekdays,
        folder
    )

    geometry = {
        "source": str(image_path),
        "period_count": len(boundaries) - 2,
        "day_count": len(weekdays),
        "columns": boundaries,
        "header": data["header"],
        "days": weekdays,
        "cells": cells,
        "status": "geometry_requires_review"
    }

    (folder / "dynamic_geometry.json").write_text(
        json.dumps(geometry, indent=2)
    )

    with (folder / "dynamic_cells.csv").open(
        "w", newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(cells[0])
        )
        writer.writeheader()
        writer.writerows(cells)

    cv2.imwrite(
        str(folder / "dynamic_cells_preview.png"),
        preview
    )

    print("\n" + "=" * 55)
    print(f"FILE: {args.name}")
    print("=" * 55)
    print("Weekdays detected:", len(weekdays))
    print("Time periods detected:", len(boundaries) - 2)
    print("Column boundaries:", boundaries)
    print("Merged/individual cells:", len(cells))

    print("\nMerged cells:")
    for cell in cells:
        if cell["last_slot"] > cell["first_slot"]:
            print(
                f"  {cell['day']:<12} "
                f"slots {cell['first_slot']}-"
                f"{cell['last_slot']}"
            )

    print(
        "\nSaved:",
        folder / "dynamic_cells_preview.png"
    )
    print(
        "Geometry is diagnostic; review before OCR."
    )


if __name__ == "__main__":
    main()
