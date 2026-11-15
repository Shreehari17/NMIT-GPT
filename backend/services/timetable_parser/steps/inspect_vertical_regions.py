"""Locate vertically merged timetable regions with geometry; no Ollama calls.

Run from the NMIT-GPT root:
  python experiments/qwen_timetable/inspect_vertical_regions.py 7A
  python experiments/qwen_timetable/inspect_vertical_regions.py 6A

This diagnostic never alters dynamic_ocr.json or the live backend.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent


def boundary_present(horizontal, y, x0, x1):
    height, width = horizontal.shape
    left = max(0, int(x0) + 7)
    right = min(width, int(x1) - 7)
    top = max(0, int(y) - 3)
    bottom = min(height, int(y) + 4)
    if right <= left or bottom <= top:
        return False
    region = horizontal[top:bottom, left:right]
    return bool((region > 0).any(axis=0).mean() >= 0.65)


def horizontal_map(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY_INV, 31, 12)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT,
                                       (max(18, image.shape[1] // 75), 1))
    return cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)


def find_groups(geometry, horizontal):
    days = geometry['days']
    cells = geometry['cells']
    period_count = geometry['period_count']
    per_day = {(c['day'], int(c['first_slot']), int(c['last_slot'])): c for c in cells}
    columns = geometry['columns']
    findings = []
    # Check every period independently: no assumed BREAK/LUNCH positions.
    for slot in range(1, period_count + 1):
        # A horizontally merged lab is not a candidate for a vertical word.
        eligible = [((d['day'], slot, slot) in per_day) for d in days]
        connected = []
        for idx in range(len(days) - 1):
            upper, lower = days[idx], days[idx + 1]
            if not (eligible[idx] and eligible[idx + 1]):
                connected.append(False)
                continue
            y = (int(upper['bottom']) + int(lower['top'])) // 2
            x0, x1 = columns[slot], columns[slot + 1]
            connected.append(not boundary_present(horizontal, y, x0, x1))
        idx = 0
        while idx < len(days):
            end = idx
            while end < len(days) - 1 and connected[end]:
                end += 1
            if end > idx:
                findings.append({'slot': slot,
                                 'days': [d['day'] for d in days[idx:end + 1]],
                                 'start_day_index': idx,
                                 'end_day_index': end,
                                 'x0': int(columns[slot]),
                                 'x1': int(columns[slot + 1]),
                                 'y0': int(days[idx]['top']),
                                 'y1': int(days[end]['bottom']),
                                 'status': 'geometric_candidate_requires_visual_review'})
            idx = end + 1
    return findings


def extract_preview(image, finding, folder, index):
    h, w = image.shape[:2]
    x0 = max(0, finding['x0'] + 4)
    x1 = min(w, finding['x1'] - 4)
    y0 = max(0, finding['y0'] + 4)
    y1 = min(h, finding['y1'] - 4)
    if x1 <= x0 or y1 <= y0:
        return None
    crop = image[y0:y1, x0:x1]
    name = f'vertical_region_{index:02d}_slot_{finding["slot"]}.png'
    cv2.imwrite(str(folder / name), crop)
    return name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('name')
    args = parser.parse_args()
    folder = ROOT / f'dynamic_grid_{args.name}' / 'page_1'
    geo_path = folder / 'dynamic_geometry.json'
    image_path = folder / 'schedule_only.png'
    geometry = json.loads(geo_path.read_text())
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(image_path)
    if geometry['period_count'] < 1 or len(geometry['days']) < 2:
        raise ValueError('Insufficient geometry for vertical merge detection')
    horizontal = horizontal_map(image)
    findings = find_groups(geometry, horizontal)
    folder_out = folder / 'vertical_regions_preview'
    folder_out.mkdir(exist_ok=True)
    for i, f in enumerate(findings, 1):
        f['image'] = extract_preview(image, f, folder_out, i)
    result = {'source': args.name, 'candidate_count': len(findings),
              'candidates': findings,
              'note': 'Geometric candidates only; no BREAK/LUNCH assignment has been made.'}
    target = folder_out / 'vertical_region_candidates.json'
    target.write_text(json.dumps(result, indent=2))
    print(f'Class sample: {args.name} | geometric regions: {len(findings)}')
    for f in findings:
        print(f'  slot {f["slot"]}, days {", ".join(f["days"])} | image: {f["image"]}')
    print('Saved:', target)
    print('No Ollama calls; original OCR files unchanged.')


if __name__ == '__main__':
    main()
