"""Discover table-like grid regions in image-based PDFs.

Usage:
  python experiments/qwen_timetable/detect_dynamic_grid.py 7A.pdf
  python experiments/qwen_timetable/detect_dynamic_grid.py 6A.pdf

Diagnostic only. Does not replace the existing extractor.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf


def group_positions(indices, max_gap=5):
    if len(indices) == 0:
        return []

    groups = [[int(indices[0])]]

    for position in indices[1:]:
        position = int(position)

        if position - groups[-1][-1] <= max_gap:
            groups[-1].append(position)
        else:
            groups.append([position])

    return [
        int(np.median(group))
        for group in groups
    ]


def detect_lines(image):
    gray = cv2.cvtColor(
        image, cv2.COLOR_RGB2GRAY
    )

    height, width = gray.shape

    ink = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        12,
    )

    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(30, width // 90), 1),
    )

    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (1, max(25, height // 90)),
    )

    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, horizontal_kernel
    )

    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, vertical_kernel
    )

    return horizontal, vertical


def inspect_region(horizontal, vertical, rect):
    x, y, w, h = rect

    h_region = horizontal[y:y+h, x:x+w]
    v_region = vertical[y:y+h, x:x+w]

    horizontal_counts = (
        h_region > 0
    ).sum(axis=1)

    vertical_counts = (
        v_region > 0
    ).sum(axis=0)

    row_positions = group_positions(
        np.flatnonzero(
            horizontal_counts >= w * 0.45
        ),
        max_gap=7,
    )

    column_positions = group_positions(
        np.flatnonzero(
            vertical_counts >= h * 0.30
        ),
        max_gap=7,
    )

    intersections = cv2.bitwise_and(
        h_region, v_region
    )

    intersection_count = cv2.connectedComponents(
        cv2.dilate(
            intersections,
            np.ones((3, 3), np.uint8),
        )
    )[0] - 1

    return {
        "bbox": [x, y, w, h],
        "horizontal_lines": [
            y + item for item in row_positions
        ],
        "vertical_lines": [
            x + item for item in column_positions
        ],
        "intersections": int(intersection_count),
        "estimated_row_intervals": max(
            0, len(row_positions) - 1
        ),
        "estimated_column_intervals": max(
            0, len(column_positions) - 1
        ),
    }


def detect_candidates(rgb):
    height, width = rgb.shape[:2]

    horizontal, vertical = detect_lines(rgb)

    combined = cv2.bitwise_or(
        horizontal, vertical
    )

    # Connect nearby line endpoints.
    connected = cv2.morphologyEx(
        combined,
        cv2.MORPH_CLOSE,
        np.ones((5, 5), np.uint8),
    )

    connected = cv2.dilate(
        connected,
        np.ones((3, 3), np.uint8),
        iterations=1,
    )

    contours, _ = cv2.findContours(
        connected,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    candidates = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)

        # Broad table-size filters, not fixed timetable
        # coordinates or a fixed number of periods.
        if w < width * 0.30:
            continue

        if h < height * 0.12:
            continue

        result = inspect_region(
            horizontal,
            vertical,
            (x, y, w, h),
        )

        if result["intersections"] < 8:
            continue

        candidates.append(result)

    candidates.sort(
        key=lambda item: (
            item["intersections"],
            item["bbox"][2] * item["bbox"][3],
        ),
        reverse=True,
    )

    return candidates, horizontal, vertical


def process(pdf_path, output_root):
    with pymupdf.open(pdf_path) as document:
        pages = len(document)

        for page_number in range(pages):
            pix = document[page_number].get_pixmap(
                matrix=pymupdf.Matrix(3, 3),
                alpha=False,
                colorspace=pymupdf.csRGB,
            )

            rgb = np.frombuffer(
                pix.samples,
                dtype=np.uint8,
            ).reshape(
                pix.height, pix.width, 3
            ).copy()

            candidates, horizontal, vertical = (
                detect_candidates(rgb)
            )

            page_dir = (
                output_root /
                f"page_{page_number + 1}"
            )

            page_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            overlay = cv2.cvtColor(
                rgb,
                cv2.COLOR_RGB2BGR,
            )

            for index, candidate in enumerate(
                candidates[:8], 1
            ):
                x, y, w, h = candidate["bbox"]

                cv2.rectangle(
                    overlay,
                    (x, y),
                    (x+w, y+h),
                    (0, 180, 0),
                    4,
                )

                cv2.putText(
                    overlay,
                    str(index),
                    (x+8, y+30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0, 0, 255),
                    3,
                )

            cv2.imwrite(
                str(page_dir / "candidates.png"),
                overlay,
            )

            cv2.imwrite(
                str(page_dir / "horizontal_lines.png"),
                horizontal,
            )

            cv2.imwrite(
                str(page_dir / "vertical_lines.png"),
                vertical,
            )

            (page_dir / "candidates.json").write_text(
                json.dumps(
                    {
                        "source": pdf_path.name,
                        "page": page_number + 1,
                        "image_size": [
                            pix.width,
                            pix.height,
                        ],
                        "candidates": candidates,
                    },
                    indent=2,
                )
            )

            print(
                f"\nPage {page_number + 1}: "
                f"{len(candidates)} table candidates"
            )

            for index, candidate in enumerate(
                candidates[:5], 1
            ):
                print(
                    f"  Candidate {index}: "
                    f"bbox={candidate['bbox']} "
                    f"rows={candidate['estimated_row_intervals']} "
                    f"columns={candidate['estimated_column_intervals']} "
                    f"intersections={candidate['intersections']}"
                )

            print(
                "Preview:",
                page_dir / "candidates.png",
            )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "pdf",
        type=Path,
    )

    args = parser.parse_args()

    if not args.pdf.is_file():
        raise FileNotFoundError(args.pdf)

    output_root = (
        Path(__file__).resolve().parent
        / f"dynamic_grid_{args.pdf.stem}"
    )

    process(args.pdf, output_root)


if __name__ == "__main__":
    main()
