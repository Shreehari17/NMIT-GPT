"""Separate the weekly schedule from adjacent document panels.

Usage:
  python experiments/qwen_timetable/isolate_schedule.py 7A
  python experiments/qwen_timetable/isolate_schedule.py 6A

Uses blank-gutter detection. No class-specific coordinates.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent


def contiguous_groups(indices):
    groups = []

    for value in indices:
        value = int(value)

        if not groups or value > groups[-1][-1] + 1:
            groups.append([value])
        else:
            groups[-1].append(value)

    return groups


def find_panel_gutter(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape

    # Count dark pixels in each vertical image column.
    dark_fraction = (gray < 170).mean(axis=0)

    positions = np.arange(width)

    # Broad search region: the side panel is generally to
    # the right of the primary timetable.
    search_area = (
        (positions > width * 0.50)
        & (positions < width * 0.90)
    )

    # Gutter columns should remain almost completely white.
    candidates = np.flatnonzero(
        (dark_fraction < 0.015) & search_area
    )

    groups = contiguous_groups(candidates)

    min_gap_width = max(6, round(width * 0.005))

    groups = [
        group for group in groups
        if len(group) >= min_gap_width
    ]

    if not groups:
        raise ValueError(
            "No sufficiently clear panel gutter detected. "
            "Manual review required."
        )

    groups.sort(key=len, reverse=True)

    # Refuse an ambiguous result instead of silently
    # selecting the wrong table boundary.
    if len(groups) > 1:
        if len(groups[1]) >= len(groups[0]) * 0.85:
            raise ValueError(
                "Multiple similar gutters detected. "
                "Cannot select the timetable safely."
            )

    gap = groups[0]

    return {
        "start": int(gap[0]),
        "end": int(gap[-1]),
        "width": len(gap),
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

    source = folder / "timetable_strip.png"

    if not source.exists():
        raise FileNotFoundError(
            f"Missing {source}. "
            "Run segment_timetable.py first."
        )

    image = cv2.imread(str(source))

    if image is None:
        raise ValueError("Unable to read timetable strip")

    height, width = image.shape[:2]

    gutter = find_panel_gutter(image)

    # Crop to the left edge of the blank separator.
    right_edge = gutter["start"]

    schedule = image[:, :right_edge].copy()

    if schedule.size == 0:
        raise ValueError("Empty schedule crop")

    preview = image.copy()

    cv2.line(
        preview,
        (right_edge, 0),
        (right_edge, height - 1),
        (0, 0, 255),
        3,
    )

    output_image = folder / "schedule_only.png"
    preview_image = folder / "panel_separator.png"
    output_json = folder / "schedule_region.json"

    cv2.imwrite(str(output_image), schedule)
    cv2.imwrite(str(preview_image), preview)

    result = {
        "source": str(source),
        "original_width": width,
        "original_height": height,
        "schedule_width": right_edge,
        "gutter": gutter,
        "status": "candidate_requires_review",
    }

    output_json.write_text(
        json.dumps(result, indent=2)
    )

    print(f"\nFILE: {args.name}")
    print(f"Detected separator: {gutter}")
    print(f"Schedule size: {right_edge} x {height}")
    print(f"Saved: {output_image}")
    print("Review the crop before using it.")


if __name__ == "__main__":
    main()
