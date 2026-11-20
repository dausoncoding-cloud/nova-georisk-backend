"""FRRIS Trend Analysis: series records and the fixed rules (docs/FRRIS_TREND_ANALYSIS_PLAN.md §2).

Pure functions: no Earth Engine here (the series come from app/services/gee/trend_series.py).

Rules implemented here:
* chronological order; every series carries its units, source, method and caveats;
* flagged points (too much no-data, low pass coverage) are kept and shown but never fitted;
* n = 2 valid points -> "Change" (Δy, %Δy), never "Trend";
* a trend line (OLS) only with n >= MIN_TREND_POINTS valid points, as a visual aid, not a forecast;
* %Δy is undefined (None, shown as "undefined") when the earlier value is 0.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable

import numpy as np
from scipy import stats

METHOD_VERSION = "frris-trend-1"
MIN_TREND_POINTS = 6
TREND_NOTE = "Trend line: ordinary least squares, a visual aid describing the past; not a forecast."
UNDEFINED = "undefined"


def _decimal_year(t: Any) -> float:
    """Years stay years; ISO dates become decimal years (day of year / days in year)."""
    if isinstance(t, (int, np.integer)):
        return float(t)
    day = date.fromisoformat(str(t)[:10])
    start, end = date(day.year, 1, 1), date(day.year + 1, 1, 1)
    return day.year + (day - start).days / (end - start).days


def percent_change(previous: float | None, current: float | None) -> float | None:
    """%Δy = (current − previous) / previous × 100; undefined (None) when the previous value is 0 or missing."""
    if previous is None or current is None or previous == 0:
        return None
    return (current - previous) / previous * 100


def change(first: dict, last: dict) -> dict[str, Any]:
    pct = percent_change(first["value"], last["value"])
    return {"from": first["t"], "to": last["t"], "from_value": first["value"], "to_value": last["value"],
            "delta": last["value"] - first["value"], "percent": pct, "percent_text": UNDEFINED if pct is None else f"{pct:.1f}%"}


def summarise(points: list[dict], *, units: str, fit_trend: bool, per: str = "year") -> dict[str, Any]:
    """The statistics block of a series under the §2 rules. ``points`` must already be in chronological order."""
    valid = [p for p in points if not p.get("flagged") and p.get("value") is not None]
    n = len(valid)
    if n < 2:
        return {"kind": "none", "n_valid": n, "text": "Fewer than two valid points: no change or trend is reported."}
    first_last = change(valid[0], valid[-1])
    if n == 2:
        return {"kind": "change", "n_valid": n, "change": first_last,
                "text": "Change between the two valid points (two points are a change, not a trend)."}
    if not fit_trend:
        return {"kind": "change", "n_valid": n, "change": first_last,
                "text": "Change between the first and last valid points; no trend line is fitted to this series."}
    if n < MIN_TREND_POINTS:
        return {"kind": "change", "n_valid": n, "change": first_last,
                "text": (f"Change between the first and last valid points. No trend line: fewer than {MIN_TREND_POINTS} "
                         "valid points.")}
    x = np.array([_decimal_year(p["t"]) for p in valid], dtype=float)
    y = np.array([p["value"] for p in valid], dtype=float)
    if np.ptp(y) == 0:
        fit = {"slope": 0.0, "intercept": float(y[0]), "r": None, "r_squared": None, "p_value": None}
    else:
        result = stats.linregress(x, y)
        fit = {"slope": float(result.slope), "intercept": float(result.intercept), "r": float(result.rvalue),
               "r_squared": float(result.rvalue ** 2), "p_value": float(result.pvalue)}
    return {"kind": "trend", "n_valid": n, "change": first_last,
            "trend": {**fit, "slope_units": f"{units} per {per}", "x": "decimal year", "note": TREND_NOTE},
            "text": f"Trend line over {n} valid points ({TREND_NOTE})"}


def series_record(*, key: str, title: str, indicator: str, units: str, points: Iterable[dict], source: str,
                  method: str, caveats: list[str], fit_trend: bool, x_kind: str, per: str = "year",
                  columns: dict[str, str] | None = None) -> dict[str, Any]:
    """One series: chronological points, flags, the statistics block and the texts every chart and table shows.

    Each point is {"t": year | ISO date, "value": float | None, "flagged": bool, "flag": str | None, ...extra columns}.
    """
    ordered = sorted(points, key=lambda p: _decimal_year(p["t"]))
    return {"key": key, "title": title, "indicator": indicator, "units": units, "x": x_kind,
            "source": source, "method": method, "caveats": list(caveats), "columns": dict(columns or {}),
            "points": ordered, "n_points": len(ordered), "n_flagged": sum(1 for p in ordered if p.get("flagged")),
            "summary": summarise(ordered, units=units, fit_trend=fit_trend, per=per)}


def dekadal_totals(daily: list[dict], last_day: str) -> list[dict]:
    """10-day rainfall totals counted back from ``last_day`` (so the last block ends on the target's last day).

    ``daily`` holds {"t": ISO date, "value": mm}. A block with missing days is flagged and its total is not computed.
    """
    by_day = {str(p["t"])[:10]: p.get("value") for p in daily}
    end = date.fromisoformat(last_day)
    days = sorted(by_day)
    if not days:
        return []
    first = date.fromisoformat(days[0])
    blocks = []
    block_end = end
    while block_end >= first:
        start = date.fromordinal(block_end.toordinal() - 9)
        span = [date.fromordinal(d).isoformat() for d in range(start.toordinal(), block_end.toordinal() + 1)]
        values = [by_day.get(d) for d in span]
        complete = start >= first and all(v is not None for v in values)
        blocks.append({"t": block_end.isoformat(), "start": start.isoformat(), "end": block_end.isoformat(),
                       "value": float(sum(values)) if complete else None, "flagged": not complete,
                       "flag": None if complete else "incomplete 10-day block"})
        block_end = date.fromordinal(start.toordinal() - 1)
    return list(reversed(blocks))


def anomaly(total_mm: float | None, climatology_mm: float | None) -> dict[str, Any]:
    """Rainfall anomaly of a window against the climatology mean of the same calendar window."""
    pct = percent_change(climatology_mm, total_mm)
    return {"total_mm": total_mm, "climatology_mean_mm": climatology_mm, "anomaly_percent": pct,
            "anomaly_text": UNDEFINED if pct is None else f"{pct:+.1f}% of the 1991–2020 mean"}
