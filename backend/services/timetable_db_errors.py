"""Translate timetable database failures into safe HTTP responses."""

import httpx
from postgrest.exceptions import APIError


def classify_save_error(exc):
    """Return (HTTP status, safe user-facing message)."""

    if isinstance(exc, httpx.TimeoutException):
        return 503, (
            "Supabase timed out. The save outcome is unknown. "
            "Refresh the existing timetable before retrying."
        )

    if isinstance(exc, httpx.RequestError):
        return 503, (
            "Could not reach Supabase. Refresh the existing "
            "timetable before retrying."
        )

    if isinstance(exc, APIError):
        code = str(getattr(exc, "code", "") or "")

        if code == "40001":
            return 409, (
                "Timetable changed since preview. "
                "Refresh and review before saving again."
            )

        if code in {"22023", "23503", "23505", "23514"}:
            return 422, (
                "Database rejected the timetable data. "
                "Check time slots, overlaps, and lab IDs."
            )

    return 503, (
        "Database save failed. Check the current timetable "
        "before attempting another save."
    )
