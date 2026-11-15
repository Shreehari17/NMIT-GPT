"""Opt-in local timetable extraction for admin preview.

Runs existing, tested vision scripts in a per-request temporary workspace to
avoid colliding with another admin upload. Never writes to the database.

Currently supports image-only, one-page, ruled PDF timetables resembling the
verified NMIT layouts. Fails closed for unsupported structures.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)
STEPS = Path(__file__).resolve().parent / 'steps'
PIPELINE = [
    ('detect_dynamic_grid.py', True),
    ('segment_timetable.py', True),
    ('isolate_schedule.py', False),
    ('detect_weekdays.py', False),
    ('build_dynamic_geometry.py', False),
    ('auto_headers.py', False),
    ('read_dynamic_cells.py', False),
    ('detect_class.py', True),
    ('extract_subject_legend.py', True),
]

REVIEW_PLACEHOLDER = '[REVIEW REQUIRED: unreadable merged cell]'

CODE_RE = re.compile(r'\b22[A-Z]{2,6}\d{2,4}[A-Z]?(?:\s*/\s*\d{2,4}[A-Z]?)*\b', re.I)


def split_content(raw: str) -> tuple[str|None, str|None, bool]:
    raw = (raw or '').strip()
    match = CODE_RE.search(raw)
    code = re.sub(r'\s*/\s*', '/', match.group()) if match else None
    activity = ((raw[:match.start()] + ' ' + raw[match.end():]).strip(' -')) if match else raw
    is_lab = bool(re.search(r'\bLAB\b', raw, re.I))
    # Class-specific codes are not inferred from the filename. `CSL` is only
    # a heuristic; review against subject legend before saving.
    if code and re.match(r'^22CSL\d', code, re.I):
        is_lab = True
    return code, activity or None, is_lab


def build_admin_payload(ocr: dict, detected_class: dict, times: dict,
                        legend: dict | None = None, vertical: list | None = None) -> dict:
    """Pure conversion: no subprocess, no external credentials, no database."""
    if not ocr.get('complete') or not times.get('all_resolved'):
        raise ValueError('Incomplete OCR or unresolved timetable headers')
    cls = detected_class.get('detected_class')
    if not cls or detected_class.get('needs_review'):
        raise ValueError('Could not reliably identify timetable class from PDF heading')
    headers = times['headers']
    periods = ocr['period_count']
    if len(headers) != periods or any(
        h.get('slot') != i or not h.get('time_slot')
        for i, h in enumerate(headers, 1)
    ):
        raise ValueError('Time headers do not match detected cell geometry')

    warnings: list[str] = []
    rows: list[dict] = []
    # Detect unusually short final time headers as a review hint, never
    # silently change a value read from the source image.
    durations = []
    for h in headers:
        try:
            start, end = h['time_slot'].split('-')
            a, b = [int(x) for x in start.split(':')], [int(x) for x in end.split(':')]
            durations.append((b[0]*60+b[1]) - (a[0]*60+a[1]))
        except (TypeError, ValueError, AttributeError):
            durations.append(None)
    instructional = sorted(d for d in durations[:-1] if d is not None and d >= 30)
    if len(instructional) >= 3 and durations[-1] is not None:
        median = instructional[len(instructional)//2]
        if 0 < durations[-1] < median * 0.65:
            warnings.append(
                f"Final period {headers[-1]['time_slot']} is unusually short "
                'relative to earlier classes; verify the printed time header.'
            )
    # Keep the exact geometric day coverage for each region. A slot alone
    # is insufficient because labs may interrupt a vertically merged label.
    vertical_by_cell = {}
    for region in (vertical or []):
        slot = region.get('slot')
        for region_day in region.get('days', []):
            key = (region_day, slot)
            if key in vertical_by_cell:
                # Ambiguous overlapping regions must remain manual review.
                vertical_by_cell[key] = None
            else:
                vertical_by_cell[key] = region
    if legend:
        for finding in legend.get('findings', []):
            warnings.append(
                f"{finding['day']} slots {finding['first_slot']}-{finding['last_slot']}: "
                + '; '.join(finding.get('issues', []))
            )
        if legend.get('legend_requires_review'):
            warnings.append('Subject legend OCR is incomplete or unverified; review course codes')
    else:
        warnings.append('Subject legend could not be verified')

    seen_cells = set()
    for cell in ocr['cells']:
        day = cell['day']
        first, last = cell['first_slot'], cell['last_slot']
        if day not in ocr['day_names'] or not (1 <= first <= last <= periods):
            raise ValueError('Invalid day/period mapping in cell OCR')
        key = (day, first, last)
        if key in seen_cells:
            raise ValueError('Duplicate cell span')
        seen_cells.add(key)
        raw = (cell.get('text') or '').strip()
        status = cell.get('status')
        if status == 'vertical_merge_review':
            # Only use a recognized shared-column word if it is an exact
            # standard activity label; never invent missing timetable data.
            candidate = (vertical_by_cell.get((day, first)) or {}) if first == last else {}
            suggestion = str(candidate.get('text') or '').strip().upper()
            if suggestion in {'BREAK','LUNCH'} and not candidate.get('uncertain', True):
                raw = suggestion
                warnings.append(f'{day} slot {first}: reconstructed shared {suggestion}; verify vertical span')
            else:
                warnings.append(f'{day} slot {first}-{last}: vertically merged label unreadable; edit the REVIEW REQUIRED row before saving')
                raw = REVIEW_PLACEHOLDER
        elif not raw:
            # A genuinely blank source cell must remain blank, not become a
            # fabricated activity. Warn but do not create an extra class.
            warnings.append(f'{day} slot {first}-{last}: blank or unreadable; verify source PDF')
            continue
        elif status != 'recognized':
            warnings.append(f'{day} slot {first}-{last}: OCR uncertain; check source PDF')
        if re.search(r'\d{3,4}\s+\d{3,4}\s*/', raw):
            warnings.append(f'{day} slot {first}-{last}: malformed elective OCR: {raw}')
        code, activity, is_lab = split_content(raw)
        for slot in range(first, last+1):
            rows.append({
                'class': cls,
                'day_of_week': day,
                'time_slot': headers[slot-1]['time_slot'],
                'subject_code': code,
                'activity': activity,
                'is_lab': is_lab,
                'lab_id': None,
            })
    if not rows:
        raise ValueError('No reviewable timetable rows extracted')
    # Check for conflicting geometries before returning any rows.
    occupied = set()
    for row in rows:
        fingerprint = (row['day_of_week'], row['time_slot'])
        if fingerprint in occupied:
            raise ValueError('Conflicting timetable cells occupy the same period')
        occupied.add(fingerprint)
    return {'rows':rows,'warnings':list(dict.fromkeys(warnings))}


def extract_local_timetable(file_bytes: bytes, filename: str) -> dict:
    """Blocking worker; call with asyncio.to_thread from FastAPI."""
    if not filename.lower().endswith('.pdf'):
        raise ValueError('Local grid mode currently supports PDF files only')
    if not file_bytes.startswith(b'%PDF-'):
        raise ValueError('Invalid PDF')
    # Explicitly reject multi-page PDFs: the detector currently selects page 1.
    # Avoid silently dropping additional timetable pages.
    import pymupdf
    with pymupdf.open(stream=file_bytes, filetype='pdf') as doc:
        if len(doc) != 1:
            raise ValueError('Local timetable mode currently requires a one-page PDF')
    # Use an opaque source name. Filename never determines the class.
    name = 'uploaded'
    # Cache persists across per-request temp workspaces. Disable with
    # NMIT_TIMETABLE_OCR_CACHE_DIR=off. No images or PDFs are cached.
    cache_setting = os.environ.get('NMIT_TIMETABLE_OCR_CACHE_DIR')
    if cache_setting is None:
        cache_setting = str(Path.home()/'.cache'/'nmit-gpt'/'timetable-ocr')
    child_env = os.environ.copy()
    if cache_setting.strip().lower() in {'off', 'none', 'disabled'}:
        child_env.pop('NMIT_TIMETABLE_OCR_CACHE_DIR', None)
    else:
        child_env['NMIT_TIMETABLE_OCR_CACHE_DIR'] = cache_setting
    with tempfile.TemporaryDirectory(prefix='nmit_tt_') as tmp:
        root = Path(tmp)
        scripts = root/'experiments'/'qwen_timetable'
        scripts.mkdir(parents=True)
        for step in STEPS.glob('*.py'):
            shutil.copy2(step, scripts/step.name)
        pdf = root / f'{name}.pdf'
        pdf.write_bytes(file_bytes)
        out = scripts / f'dynamic_grid_{name}' / 'page_1'
        for step, takes_pdf in PIPELINE:
            arg = str(pdf) if takes_pdf else name
            command = [sys.executable, str(scripts/step), arg]
            logger.info('Local timetable stage START: %s', step)
            stage_started = time.monotonic()
            proc = subprocess.run(
                command, cwd=root, capture_output=True, text=True,
                timeout=1200, check=False, env=child_env,
            )
            logger.info('Local timetable stage END: %s (%.1fs)', step, time.monotonic()-stage_started)
            if step == 'read_dynamic_cells.py':
                for line in proc.stdout.splitlines():
                    if line.startswith('OCR cache hits:'):
                        logger.info('%s', line)
            if step == 'detect_weekdays.py':
                weekday_file = out / 'weekday_rows.json'
                if weekday_file.exists():
                    weekday_data = json.loads(weekday_file.read_text())
                    logger.warning(
                        'Weekday diagnosis: days=%s, warnings=%s, header=%s, other_rows=%s',
                        [d.get('day') for d in weekday_data.get('days', [])],
                        weekday_data.get('warnings', []),
                        weekday_data.get('header'),
                        weekday_data.get('other_rows', [])
                    )
                    logger.info('Weekday detector output: %s', proc.stdout[-3000:])

            if proc.returncode:
                logger.warning('Local timetable stage %s failed: %s %s', step, proc.stderr[-1800:], proc.stdout[-1800:])
                raise ValueError(f'Local parser stage {step} failed; document may be unsupported or Ollama unavailable')
        # Refine the legend only if the initial full-image OCR looks inconsistent.
        original = json.loads((out/'subject_legend_review.json').read_text())
        if len(original.get('findings',[])) > 2:
            for step in ('refine_subject_legend.py',):
                proc = subprocess.run(
                    [sys.executable,str(scripts/step),name], cwd=root,
                    capture_output=True,text=True,timeout=1200,check=False
                )
                if proc.returncode:
                    logger.warning('Legend refinement failed; use only original OCR warnings')
        proc = subprocess.run(
            [sys.executable,str(scripts/'validate_subject_codes.py'),name],
            cwd=root,capture_output=True,text=True,timeout=120,check=False
        )
        if proc.returncode:
            raise ValueError('Subject code validation failed')
        # Best-effort: warnings will remain even if shared-label OCR fails.
        proc = subprocess.run(
            [sys.executable,str(scripts/'auto_vertical.py'),name],
            cwd=root,capture_output=True,text=True,timeout=240,check=False
        )
        if proc.returncode:
            logger.warning('Shared vertical labels could not be reconstructed')
        ocr=json.loads((out/'dynamic_ocr.json').read_text())
        klass=json.loads((scripts/f'class_detection_{name}'/'class_detection.json').read_text())
        times=json.loads((out/'auto_time_headers.json').read_text())
        legend=json.loads((out/'subject_validation_final.json').read_text())
        vert_path=out/'vertical_review.json'
        vert=json.loads(vert_path.read_text()) if vert_path.exists() else []
        result=build_admin_payload(ocr,klass,times,legend,vert)
        result['warnings'].insert(0,'Local vision extraction is experimental: carefully verify all subjects, times and merged spans before saving.')
        return result
