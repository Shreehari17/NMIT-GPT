"""Find timetable region between document header and subject legend.

Uses detected table candidate and dark-band analysis.
Diagnostic: does not change existing extraction results.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf

BASE = Path(__file__).resolve().parent


def group_rows(indices):
    groups = []
    for number in indices:
        number = int(number)
        if not groups or number > groups[-1][-1] + 1:
            groups.append([number])
        else:
            groups[-1].append(number)
    return groups


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    source = args.pdf

    if not source.is_file():
        raise FileNotFoundError(source)

    stem = source.stem
    results_dir = BASE / f"dynamic_grid_{stem}" / "page_1"

    candidate_path = results_dir / "candidates.json"

    if not candidate_path.exists():
        raise FileNotFoundError(
            "Run detect_dynamic_grid.py first"
        )

    data = json.loads(candidate_path.read_text())
    candidates = data["candidates"]

    if not candidates:
        raise ValueError("No table candidates found")

    with pymupdf.open(source) as document:
        pix = document[0].get_pixmap(
            matrix=pymupdf.Matrix(3, 3),
            colorspace=pymupdf.csRGB,
            alpha=False,
        )
        image = np.frombuffer(
            pix.samples, dtype=np.uint8
        ).reshape(pix.height, pix.width, 3).copy()

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    # Use the largest supported candidate, not the whole page.
    x, y, w, h = candidates[0]["bbox"]

    # Inspect the left half, where timetable and legend
    # title bands occur; avoid dependence on the dates panel.
    x0 = x + int(w * 0.05)
    x1 = x + int(w * 0.48)

    region = gray[y:y+h, x0:x1]

    if region.size == 0:
        raise ValueError("Empty candidate region")

    darkness = (region < 135).mean(axis=1)

    # A title band covers most of the sampled horizontal width.
    selected = np.flatnonzero(darkness > 0.55)
    groups = group_rows(selected)

    # Reject thin table rules.
    bands = [
        (y + group[0], y + group[-1])
        for group in groups
        if len(group) >= 8
    ]

    print("Detected dark bands:", bands)

    if len(bands) < 2:
        raise ValueError(
            "Could not identify two header bands. "
            "This layout needs another segmentation strategy."
        )

    # The first two qualifying bands are tentative boundaries.
    top_band, legend_band = bands[:2]

    top = top_band[1] + 1
    bottom = legend_band[0]

    if bottom <= top:
        raise ValueError("Invalid timetable region")

    # At this stage we retain the full candidate width.
    # Side-panel separation is a subsequent step.
    crop = image[top:bottom, x:x+w]

    overlay = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    cv2.rectangle(
        overlay,
        (x, top),
        (x+w, bottom),
        (0, 180, 0),
        4,
    )

    output = {
        "source": source.name,
        "page": 1,
        "candidate_bbox": [x, y, w, h],
        "top_header_band": list(top_band),
        "legend_header_band": list(legend_band),
        "timetable_strip_bbox": [
            x, top, w, bottom-top
        ],
        "status": "candidate_requires_review",
    }

    cv2.imwrite(
        str(results_dir / "timetable_strip.png"),
        cv2.cvtColor(crop, cv2.COLOR_RGB2BGR),
    )

    cv2.imwrite(
        str(results_dir / "segmentation_overlay.png"),
        overlay,
    )

    (results_dir / "segmentation.json").write_text(
        json.dumps(output, indent=2)
    )

    print("Timetable strip:", output["timetable_strip_bbox"])
    print("Saved:", results_dir / "timetable_strip.png")
    print("Note: Side panel is still included.")


if __name__ == "__main__":
    main()
