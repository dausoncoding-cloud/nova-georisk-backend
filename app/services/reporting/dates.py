"""User-facing date wording (P6, 2026-11-16): every period shown to people is inclusive.

The API, provenance.json and the science keep end-exclusive windows ({"start": "2024-05-24", "end": "2024-05-26"}
covers 24 and 25 May). Only presentation goes through this module: the last day shown is the exclusive end minus
one day, in the same short format as the browser ("24–25 May 2024", "28 Aug – 2 Sep 2022").
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _day(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def last_day(exclusive_end: Any) -> date | None:
    """The last day included in a window whose API end is exclusive."""
    end = _day(exclusive_end)
    return end - timedelta(days=1) if end else None


def day_text(value: Any) -> str:
    day = _day(value)
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}" if day else "not recorded"


def _range(first: date, last: date, joiner: str, *, between: bool = False) -> str:
    if first == last:
        return day_text(first)
    if first.year != last.year:
        return f"{day_text(first)}{joiner}{day_text(last)}"
    if first.month != last.month:
        return f"{first.day} {MONTHS[first.month - 1]}{joiner}{day_text(last)}"
    return f"{first.day}{' and ' if between else '–'}{day_text(last)}"


def period_text(start: Any, exclusive_end: Any) -> str | None:
    """"24–25 May 2024" for start 2024-05-24, API end 2024-05-26."""
    first, last = _day(start), last_day(exclusive_end)
    if not first or not last or last < first:
        return None
    return _range(first, last, " – ")


def period_dict_text(period: Any) -> str | None:
    return period_text(period.get("start"), period.get("end")) if isinstance(period, dict) else None


def between_text(start: Any, exclusive_end: Any) -> str:
    """"between 21 and 22 May 2024" (or "on 21 May 2024" for a one-day window), for messages."""
    first, last = _day(start), last_day(exclusive_end)
    if not first or not last or last < first:
        return f"between {start} and {exclusive_end}"
    if first == last:
        return f"on {day_text(first)}"
    return f"between {_range(first, last, ' and ', between=True)}"
