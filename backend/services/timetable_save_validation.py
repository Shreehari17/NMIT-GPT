"""Pure input checks for admin timetable saving. No credentials or database calls."""
import re
from collections import Counter

DAYS = {'monday': 'Monday', 'tuesday': 'Tuesday', 'wednesday': 'Wednesday',
        'thursday': 'Thursday', 'friday': 'Friday', 'saturday': 'Saturday', 'sunday': 'Sunday'}
TIME = re.compile(r'^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$')
REVIEW = re.compile(r'REVIEW\s+REQUIRED|\[\s*REVIEW', re.I)
MAX_ROWS = 500
LAB_FK = re.compile(r'^LAB[1-9][0-9]*$')
DEPARTMENT = re.compile(r'^[A-Za-z][A-Za-z0-9 &/\-]{0,49}$')
SUBGROUP = re.compile(r'^[A-Za-z0-9]+-[A-Za-z][A-Za-z0-9]*$')


def validate_department(value):
    dept = tidy(value, 50)
    if not dept or not DEPARTMENT.fullmatch(dept):
        raise ValueError('department is required (e.g. CSE)')
    return dept


def is_subgroup(cls):
    return bool(SUBGROUP.fullmatch(cls))



def tidy(value, limit=250):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('Text fields must contain strings')
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f'Text field exceeds {limit} characters')
    return value or None


def validate_save_rows(rows):
    """Return (one class name, normalized rows), raising ValueError on ANY defect."""
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError(f'Provide between 1 and {MAX_ROWS} timetable rows')
    errors, cleaned, keys = [], [], set()
    for idx, raw in enumerate(rows, 1):
        if not isinstance(raw, dict):
            errors.append(f'Row {idx}: expected an object')
            continue
        try:
            cls = tidy(raw.get('class'), 80)
            day_input = tidy(raw.get('day_of_week'), 30)
            day = DAYS.get((day_input or '').lower())
            time_input = tidy(raw.get('time_slot'), 30)
            code = tidy(raw.get('subject_code'), 200)
            activity = tidy(raw.get('activity'), 500)
            lab_id = tidy(raw.get('lab_id'), 120)
            is_lab = raw.get('is_lab', False)
            if not isinstance(is_lab, bool):
                raise ValueError('is_lab must be true or false')
            if not cls or not re.fullmatch(r'[\w /()\-.]+', cls, re.UNICODE):
                raise ValueError('class is missing or contains invalid characters')
            if not day:
                raise ValueError('day must be a valid weekday')
            match = TIME.fullmatch(time_input or '')
            if not match:
                raise ValueError('time_slot must be HH:MM-HH:MM (24-hour)')
            h1, m1, h2, m2 = map(int, match.groups())
            start, end = h1 * 60 + m1, h2 * 60 + m2
            if max(h1, h2) > 23 or max(m1, m2) > 59 or end <= start:
                raise ValueError('invalid or non-increasing time interval')
            slot = f'{h1:02d}:{m1:02d}-{h2:02d}:{m2:02d}'
            if not (code or activity):
                raise ValueError('subject_code or activity is required')
            if any(REVIEW.search(x or '') for x in (code, activity, lab_id)):
                raise ValueError('unresolved REVIEW REQUIRED placeholder')
            if lab_id and not LAB_FK.fullmatch(lab_id):
                raise ValueError('lab_id must be a valid ID such as LAB3; keep room descriptions in activity')
            if lab_id and not is_lab:
                raise ValueError('lab_id supplied but is_lab is false')
            key = (cls.casefold(), day, slot)
            if key in keys:
                raise ValueError('duplicate class/day/time slot')
            keys.add(key)
            cleaned.append({'class': cls, 'day_of_week': day, 'time_slot': slot,
                            'subject_code': code, 'activity': activity,
                            'is_lab': is_lab, 'lab_id': lab_id})
        except ValueError as exc:
            errors.append(f'Row {idx}: {exc}')
    if errors:
        raise ValueError('; '.join(errors[:12]) + (f'; and {len(errors)-12} more' if len(errors) > 12 else ''))
    classes = {r['class'] for r in cleaned}
    if len(classes) != 1:
        raise ValueError('Save one class at a time; split mixed-class uploads before saving')
    cls = next(iter(classes))
    for day in DAYS.values():
        intervals = []
        for r in cleaned:
            if r['day_of_week'] != day:
                continue
            a, b = r['time_slot'].split('-')
            start = int(a[:2]) * 60 + int(a[3:])
            end = int(b[:2]) * 60 + int(b[3:])
            intervals.append((start, end))
        intervals.sort()
        for prior, curr in zip(intervals, intervals[1:]):
            if curr[0] < prior[1]:
                raise ValueError(f'{day}: overlapping time slots {prior} and {curr}')
    return cls, cleaned
