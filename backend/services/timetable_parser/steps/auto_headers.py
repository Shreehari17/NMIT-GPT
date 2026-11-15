"""Read time headers from detected dynamic geometry, with targeted OCR verification.

Never fix a period by assuming a particular clock time. Suspicious last periods
are independently re-read from alternative crops and rejected if unresolved.
"""
import argparse
import json
from pathlib import Path

import cv2
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
from detect_time_headers import recognize_header, normalize_time
from resolve_time_headers import resolve


def duration(slot):
    try:
        a, b = slot.split('-')
        def minutes(t):
            h, m = map(int, t.split(':'))
            return 60*h + m
        return minutes(b) - minutes(a)
    except (AttributeError, TypeError, ValueError):
        return None


def suspicious_final(headers):
    if len(headers) < 4 or not headers[-1].get('time_slot'):
        return False
    durations = [duration(h.get('time_slot')) for h in headers]
    previous = sorted(d for d in durations[:-1] if d is not None and d >= 30)
    if len(previous) < 3:
        return False
    last = durations[-1]
    return last is not None and (last <= 0 or last < previous[len(previous)//2]*0.65)


def make_crop(image, columns, header, slot, variant):
    # Alternative variants intentionally change the source crop, not just OCR randomness.
    gap = 3 if variant == 'normal' else (1 if variant == 'wide' else 5)
    top_pad = 3 if variant != 'wide' else 1
    bounds = (columns[slot]+gap, header['top']+top_pad,
              columns[slot+1]-gap, header['bottom']-top_pad)
    crop = image.crop(bounds)
    if min(crop.size) <= 0:
        raise ValueError(f'Invalid header crop slot={slot}, variant={variant}')
    crop = ImageOps.expand(crop, border=14 if variant != 'wide' else 24, fill='white')
    scale = 3 if variant == 'normal' else (4 if variant == 'wide' else 5)
    crop = crop.resize((crop.width*scale, crop.height*scale), Image.Resampling.LANCZOS)
    if variant == 'sharp':
        crop = ImageEnhance.Sharpness(crop).enhance(2.2)
        crop = ImageEnhance.Contrast(crop).enhance(2.0)
    else:
        crop = ImageEnhance.Contrast(crop).enhance(1.5)
    return crop


def reread_suspicious_final(image, columns, header, results, base):
    """Two independent crop variants must agree before replacing suspicious OCR."""
    slot = len(results)
    second_reads = []
    for variant in ('wide', 'sharp'):
        path = base / f'time_header_{slot:02d}_{variant}.png'
        make_crop(image, columns, header, slot, variant).save(path)
        reread = recognize_header(path)
        second_reads.append({'variant': variant, **reread})
        print(f'Verifying suspicious final header ({variant}): {reread!r}', flush=True)
    (base/'time_header_review.json').write_text(json.dumps({
        'slot': slot,
        'original': results[-1],
        'alternatives': second_reads,
    }, indent=2))
    # Require agreement of two alternate image crops, no filename/class heuristics.
    # OCR may replace the separator between two clock times
    # with a colon. Accept only the exact four-component pattern.
    import re

    def normalize_verified_time(raw):
        raw = str(raw or '').strip()
        match = re.fullmatch(
            r'(\d{1,2}):(\d{2})\s*:\s*(\d{1,2}):(\d{2})',
            raw
        )
        if match:
            h1, m1, h2, m2 = match.groups()
            raw = f'{h1}:{m1}-{h2}:{m2}'
        return normalize_time(raw)

    normals = [
        normalize_verified_time(r['raw'])
        if not r['uncertain'] else None
        for r in second_reads
    ]
    if normals[0] is None or normals[0] != normals[1]:
        raise ValueError('Final time header OCR ambiguous: alternative crop readings disagree; manual review required')
    results[-1] = {'slot': slot, 'raw': normals[0], 'needs_review': False,
                   'verified_by': 'two_independent_crops'}
    corrected = resolve(results)
    if not all(x.get('time_slot') and not x['needs_review'] for x in corrected):
        raise ValueError('Re-read time header does not connect chronologically; manual review required')
    if suspicious_final(corrected):
        raise ValueError('Final time header remains suspicious after independent OCR verification')
    return corrected


def main():
    arg = argparse.ArgumentParser()
    arg.add_argument('name')
    name = arg.parse_args().name
    base = Path(__file__).resolve().parent / f'dynamic_grid_{name}' / 'page_1'
    geo = json.loads((base/'dynamic_geometry.json').read_text())
    bgr = cv2.imread(str(base/'schedule_only.png'))
    if bgr is None:
        raise ValueError('Schedule image missing')
    image = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    columns, header = geo['columns'], geo['header']
    results = []
    for i in range(1, len(columns)-1):
        crop = make_crop(image, columns, header, i, 'normal')
        path = base / f'time_header_{i:02d}.png'
        crop.save(path)
        r = recognize_header(path)
        results.append({'slot': i, 'raw': r['raw'],
                        'needs_review': r['uncertain'] or normalize_time(r['raw']) is None})
        print('Time header', i, repr(r['raw']), flush=True)
    resolved = resolve(results)
    verified = False
    if suspicious_final(resolved):
        resolved = reread_suspicious_final(image, columns, header, results, base)
        verified = True
    payload = {
        'headers': resolved,
        'period_count': len(results),
        'all_resolved': all(x.get('time_slot') and not x['needs_review'] for x in resolved),
        'final_header_reverified': verified,
    }
    (base/'auto_time_headers.json').write_text(json.dumps(payload, indent=2))
    if not payload['all_resolved']:
        raise ValueError('One or more time headers cannot be reliably resolved')


if __name__ == '__main__':
    main()
