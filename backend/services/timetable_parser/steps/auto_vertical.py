"""Geometrically bounded recognition of vertically printed timetable labels.

Each candidate covers an actual uninterrupted vertical cell region, rather
than a guessed BREAK/LUNCH period. No timetable OCR rows are mutated.
"""
import argparse
import json
from pathlib import Path
import cv2
from inspect_vertical_regions import find_groups, horizontal_map, extract_preview
from read_timetable_cells import read_with_retries


def recognize_word(image_path):
    # Only accept exact recognized words; never infer from slot or timetable.
    result = read_with_retries(image_path)
    text = str(result.get('text') or '').strip().upper()
    text = ' '.join(text.split())
    if text in {'BREAK', 'LUNCH'} and not result.get('uncertain', True):
        return text, False
    # A vertically stacked word sometimes comes back spaced out.
    compact = ''.join(text.split())
    if compact in {'BREAK', 'LUNCH'} and not result.get('uncertain', True):
        return compact, False
    return text, True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('name')
    name = parser.parse_args().name
    base = Path(__file__).resolve().parent / f'dynamic_grid_{name}' / 'page_1'
    geo = json.loads((base / 'dynamic_geometry.json').read_text())
    bgr = cv2.imread(str(base / 'schedule_only.png'))
    if bgr is None:
        raise FileNotFoundError(base / 'schedule_only.png')
    regions = find_groups(geo, horizontal_map(bgr))
    folder = base / 'vertical_regions_preview'
    folder.mkdir(exist_ok=True)
    output = []
    for idx, region in enumerate(regions, 1):
        image_name = extract_preview(bgr, region, folder, idx)
        text, uncertain = '', True
        if image_name:
            try:
                text, uncertain = recognize_word(folder / image_name)
            except Exception as exc:
                print(f"Vertical region OCR unavailable: {type(exc).__name__}: {exc}", flush=True)
        output.append({
            'slot': region['slot'], 'days': region['days'],
            'text': text, 'uncertain': uncertain,
            'image': f'vertical_regions_preview/{image_name}' if image_name else None,
            'method': 'geometry-bounded-single-region-ocr',
        })
        print(f"Vertical region slot {region['slot']} days {region['days']}: "
              f"{text!r}, uncertain={uncertain}", flush=True)
    (base / 'vertical_review.json').write_text(json.dumps(output, indent=2))
    print('Vertical regions:', len(output), flush=True)


if __name__ == '__main__':
    main()
