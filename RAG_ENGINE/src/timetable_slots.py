"""Compatibility for legacy 12-hour-looking and new 24-hour timetable slots.

Seven teaching periods are intentionally distinct from the nine PDF columns
(which include BREAK and LUNCH). This module does not change database rows.
"""
import re

TEACHING_SLOTS = (
    "09:00-09:55", "10:05-11:00", "11:00-11:55",
    "12:35-13:30", "13:30-14:25", "14:25-15:20", "15:20-16:15",
)
LEGACY_AFTERNOON = {
    "12:35-13:30": "12:35-01:30",
    "13:30-14:25": "01:30-02:25",
    "14:25-15:20": "02:25-03:20",
    "15:20-16:15": "03:20-04:15",
}


def canonical_slot(slot):
    """Normalize complete known legacy/modern intervals; leave unknown untouched."""
    value = str(slot or "").strip()
    for modern, legacy in LEGACY_AFTERNOON.items():
        if value == legacy:
            return modern
    return value


def slot_variants(slot):
    """Safe exact-match database alternatives; no wildcard query."""
    modern = canonical_slot(slot)
    old = LEGACY_AFTERNOON.get(modern)
    return [modern, old] if old and old != modern else [modern]


def slot_sort_key(slot):
    """Order by actual clock start, handling both legacy and modern values."""
    value = canonical_slot(slot)
    match = re.fullmatch(r"(\d{2}):(\d{2})-(\d{2}):(\d{2})", value)
    if match:
        a, b, c, d = map(int, match.groups())
        if 0 <= a <= 23 and 0 <= b <= 59 and 0 <= c <= 23 and 0 <= d <= 59:
            return (a * 60 + b, c * 60 + d)
    return (9999, 9999)


def teaching_period(slot):
    modern = canonical_slot(slot)
    try:
        return str(TEACHING_SLOTS.index(modern) + 1)
    except ValueError:
        return "?"
