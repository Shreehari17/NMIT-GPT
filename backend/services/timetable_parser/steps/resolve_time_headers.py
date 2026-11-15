"""Resolve OCR timetable headers into chronological 24-hour periods.

Usage:
    python experiments/qwen_timetable/resolve_time_headers.py 7A
    python experiments/qwen_timetable/resolve_time_headers.py 6A

Uses extracted header data, not a hardcoded timetable.
"""
import argparse
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent

TIME_PATTERN = re.compile(
    r"^\s*(\d{1,2}):(\d{2})\s*-\s*"
    r"(\d{1,2}):(\d{2})\s*$"
)


def candidates(hour, minute):
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Invalid clock time")

    if hour == 0 or hour >= 13:
        return [hour * 60 + minute]

    if hour == 12:
        return [12 * 60 + minute]

    return [
        hour * 60 + minute,
        (hour + 12) * 60 + minute,
    ]


def format_clock(minutes):
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}"


def resolve(headers):
    output = []
    previous_end = None

    for index, item in enumerate(headers, 1):
        raw = item.get("raw", "")
        match = TIME_PATTERN.fullmatch(raw)

        if not match:
            output.append({
                "slot": index,
                "raw": raw,
                "time_slot": None,
                "needs_review": True,
                "reason": "Unreadable time range",
            })
            previous_end = None
            continue

        h1, m1, h2, m2 = map(int, match.groups())

        try:
            starts = candidates(h1, m1)
            ends = candidates(h2, m2)
        except ValueError:
            output.append({
                "slot": index,
                "raw": raw,
                "time_slot": None,
                "needs_review": True,
                "reason": "Invalid time value",
            })
            previous_end = None
            continue

        pairs = [
            (start, end)
            for start in starts
            for end in ends
            if start < end <= 24 * 60
        ]

        # College time periods should not be implausibly long.
        pairs = [
            pair for pair in pairs
            if pair[1] - pair[0] <= 180
        ]

        if previous_end is not None:
            # Exact continuity takes priority over guesses.
            continuous = [
                pair for pair in pairs
                if pair[0] == previous_end
            ]

            if continuous:
                chosen = min(
                    continuous,
                    key=lambda pair: pair[1],
                )
                reason = ""
            else:
                chosen = None
                reason = (
                    "Time does not connect to preceding period; "
                    "manual verification required"
                )
        else:
            # Start-of-day convention for morning timetables.
            morning = [
                pair for pair in pairs
                if 8 * 60 <= pair[0] < 12 * 60
            ]

            chosen = (
                min(morning, key=lambda pair: pair[0])
                if morning
                else None
            )

            reason = (
                "" if chosen else
                "First-period AM/PM is ambiguous; "
                "manual verification required"
            )

        if chosen is None:
            output.append({
                "slot": index,
                "raw": raw,
                "time_slot": None,
                "needs_review": True,
                "reason": reason,
            })
            previous_end = None
            continue

        start, end = chosen

        output.append({
            "slot": index,
            "raw": raw,
            "start_time": format_clock(start),
            "end_time": format_clock(end),
            "time_slot": (
                f"{format_clock(start)}-"
                f"{format_clock(end)}"
            ),
            "needs_review": (
                bool(item.get("needs_review"))
            ),
            "reason": (
                "Original header OCR flagged uncertainty"
                if item.get("needs_review")
                else reason
            ),
        })

        previous_end = end

    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    args = parser.parse_args()

    folder = BASE / f"cells_{args.name}"
    source = folder / "time_headers.json"

    data = json.loads(source.read_text())

    if not data.get("complete"):
        raise ValueError(
            "Time-header extraction is incomplete"
        )

    results = resolve(data["headers"])

    target = folder / "time_headers_resolved.json"

    target.write_text(
        json.dumps({
            "source_pdf": data["source_pdf"],
            "period_count": len(results),
            "all_resolved": all(
                x["time_slot"] is not None
                and not x["needs_review"]
                for x in results
            ),
            "headers": results,
        }, indent=2)
    )

    print(f"\nCLASS/FILE: {args.name}")
    print("=" * 58)

    for item in results:
        print(
            f"Slot {item['slot']:02d}: "
            f"{item['raw']:<17} -> "
            f"{item['time_slot'] or 'REVIEW'}"
        )

        if item["needs_review"]:
            print("  WARNING:", item["reason"])

    print("\nSaved:", target)


if __name__ == "__main__":
    main()
