"""Trend Analysis charts (plan §2, §5): line graphs, X = time, Y = indicator, units and source on every chart.

Same figure style as the hazard graphs (report font, 16 cm wide, 300 dpi PNG + SVG). Valid points are joined by a
line; flagged points are drawn hollow and not joined or fitted; the OLS line (n >= 6 only) is dashed and labelled as a
visual aid, not a forecast.
"""
from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from app.services.firris.trends import _decimal_year  # noqa: E402
from app.services.reporting.hazard_figures import DPI, GRID, INK, INK_2, STYLE, WIDTH_IN, _save  # noqa: E402

FLAG = "#9a9a9a"


def _x(series: dict, t):
    return t if series.get("x") == "year" else date.fromisoformat(str(t)[:10])


def segments(points: list[dict]) -> list[list[dict]]:
    """Runs of consecutive valid points: a flagged or missing point breaks the line, so it shows as a gap."""
    runs: list[list[dict]] = [[]]
    for point in points:
        if point.get("flagged") or point.get("value") is None:
            if runs[-1]:
                runs.append([])
        else:
            runs[-1].append(point)
    return [run for run in runs if run]


def _draw(ax, series: dict[str, Any], *, colour=INK, label: str | None = None) -> None:
    points = series.get("points") or []
    valid = [p for p in points if not p.get("flagged") and p.get("value") is not None]
    flagged = [p for p in points if p.get("flagged") and p.get("value") is not None]
    marker = "o" if len(points) <= 60 else None
    for index, run in enumerate(segments(points)):
        ax.plot([_x(series, p["t"]) for p in run], [p["value"] for p in run], color=colour, lw=1.4, marker=marker,
                ms=3.2, label=(label or series.get("indicator")) if index == 0 else None)
    if flagged:
        ax.plot([_x(series, p["t"]) for p in flagged], [p["value"] for p in flagged], ls="none", marker="o", ms=3.6,
                mfc="white", mec=FLAG, mew=1, label="Flagged (shown, not used)")
    summary = series.get("summary") or {}
    if summary.get("kind") == "trend" and summary["trend"].get("slope") is not None:
        fit = summary["trend"]
        xs = np.array([_decimal_year(p["t"]) for p in valid])
        line_x = np.array([xs.min(), xs.max()])
        line_y = fit["intercept"] + fit["slope"] * line_x
        if series.get("x") == "year":
            ax.plot(line_x, line_y, ls="--", lw=1, color=INK_2, label="Trend line (visual aid; not a forecast)")
        else:
            ends = [valid[0]["t"], valid[-1]["t"]]
            ax.plot([_x(series, t) for t in ends], line_y, ls="--", lw=1, color=INK_2,
                    label="Trend line (visual aid; not a forecast)")
    ax.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)


def series_figure(series: dict[str, Any], stem: Path) -> dict[str, Path]:
    """One series as a line graph with axis titles, units, the statistics line and the source line."""
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(WIDTH_IN, WIDTH_IN * 0.42))
        _draw(ax, series)
        ax.set_title(series["title"])
        ax.set_xlabel("Year" if series.get("x") == "year" else "Date")
        ax.set_ylabel(f"{series.get('axis_label') or series['indicator']} ({series['units']})")
        ax.set_ylim(bottom=0)
        ax.legend(loc="upper left", frameon=False)
        statistics = _wrap(_statistics_line(series))
        fig.text(0.01, -0.06, statistics, fontsize=7, ha="left", va="top")
        fig.text(0.01, -0.06 - 0.055 * (statistics.count("\n") + 1) - 0.02, _wrap("Source: " + series["source"]),
                 fontsize=6.5, ha="left", va="top", color="#555")
        fig.autofmt_xdate() if series.get("x") == "date" else None
        return _save(fig, stem)


def rainfall_figure(daily: dict[str, Any], dekadal: dict[str, Any], anomaly: dict[str, Any] | None, stem: Path) -> dict[str, Path]:
    """Daily rainfall and 10-day totals (two panels, shared time axis), with the anomaly in the footer."""
    with plt.rc_context(STYLE):
        fig, (top, bottom) = plt.subplots(2, 1, sharex=True, figsize=(WIDTH_IN, WIDTH_IN * 0.62))
        _draw(top, daily, label="Daily rainfall")
        top.set_ylabel(f"Rainfall ({daily['units']})")
        top.set_title(daily["title"])
        top.set_ylim(bottom=0)
        _draw(bottom, dekadal, colour="#009E73", label="10-day total")
        bottom.set_ylabel(f"10-day total ({dekadal['units'].split(' per ')[0]})")
        bottom.set_xlabel("Date")
        bottom.set_ylim(bottom=0)
        for ax in (top, bottom):
            ax.legend(loc="upper left", frameon=False)
        footer = "No trend line is fitted to rainfall."
        if anomaly and anomaly.get("status") == "assessed":
            total = "—" if anomaly.get("total_mm") is None else f"{anomaly['total_mm']:.1f} mm"
            footer = (f"{anomaly['window_days']}-day total {total}; 1991–2020 mean of the same window "
                      f"{anomaly['climatology_mean_mm']:.1f} mm; anomaly {anomaly['anomaly_text']}. " + footer)
        footer = _wrap(footer)
        fig.text(0.01, -0.03, footer, fontsize=7, ha="left", va="top")
        fig.text(0.01, -0.03 - 0.036 * (footer.count("\n") + 1) - 0.015, _wrap("Source: " + daily["source"]),
                 fontsize=6.5, ha="left", va="top", color="#555")
        fig.autofmt_xdate()
        return _save(fig, stem)


def _wrap(text: str, width: int = 130) -> str:
    """Keep footer text inside the 16 cm figure width (a long line would widen the saved image)."""
    return "\n".join(textwrap.wrap(text, width))


def _statistics_line(series: dict[str, Any]) -> str:
    summary = series.get("summary") or {}
    units = series.get("units", "")
    parts = [f"n = {summary.get('n_valid', 0)} valid of {series.get('n_points', 0)} points"]
    change = summary.get("change")
    if change:
        parts.append(f"change {change['from']} → {change['to']}: {change['delta']:+.2f} {units} ({change['percent_text']})")
    if summary.get("kind") == "trend":
        fit = summary["trend"]
        parts.append(f"statistically significant trend {fit['slope']:+.3f} {fit['slope_units']}, "
                     f"R² = {fit['r_squared']:.2f}, p = {fit['p_value']:.3g} (dashed line; not a forecast)")
    elif summary.get("kind") == "no_significant_trend":
        fit = summary["trend"]
        stats_text = ("p and R² undefined" if fit.get("p_value") is None else
                      f"p = {fit['p_value']:.3g}, R² = {fit['r_squared']:.2f}")
        parts.append(f"no statistically significant trend ({stats_text}); no trend line drawn")
    else:
        parts.append(summary.get("text", ""))
    return "; ".join(p for p in parts if p)
