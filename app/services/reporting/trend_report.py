"""Report section of the Trend Analysis (docs/FRRIS_TREND_ANALYSIS_PLAN.md §5).

Written after the accuracy assessment (and after the hazard and exposure sections when the run has them), numbered by
the report. Context next to the flood map: it describes the past and is never a forecast or an accuracy measure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.firris import trends
from app.services.reporting.trend_figures import _statistics_line, rainfall_figure, series_figure

SECTION = "Trend analysis"
FIGURE_LABELS = {"trend_surface_water_annual": "Trend analysis — annual surface water (JRC)",
                 "trend_rainfall": "Trend analysis — rainfall and 10-day totals (CHIRPS)",
                 "trend_sar_open_water": "Trend analysis — SAR open water per Sentinel-1 pass"}


def _num(value, digits=2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def _caveats(writer, series: dict[str, Any]) -> None:
    for text in series.get("caveats") or []:
        writer.para(f"• {text}")


def _not_available(writer, series: dict[str, Any]) -> None:
    writer.para(f"{series.get('title', 'Series')}: not available. {series.get('reason') or ''}".strip())


def trend_section(writer, output_directory: Path, record: dict[str, Any] | None, *, number: int) -> dict[str, tuple[Path, str]]:
    """Write the section and return its figure files (for the downloads list and the package)."""
    if not record:
        return {}
    writer.heading(f"{number}. {SECTION}")
    if record.get("status") != "assessed":
        writer.para(f"Trend analysis: not available. {record.get('reason') or ''}".strip())
        return {}
    writer.para("Three series describe the area over time: annual surface water since 1984 (JRC), rainfall before the "
                "target date (CHIRPS), and SAR open water on each Sentinel-1 pass of the run's orbit. Each chart gives its "
                f"units and source. Rules: a trend line is drawn only with at least {trends.MIN_TREND_POINTS} valid points "
                "and is a visual aid describing the past, not a forecast; two points are reported as a change, never a trend; "
                "flagged points are shown but not used; a percentage change from 0 is undefined.")
    figures: dict[str, tuple[Path, str]] = {}
    series = record.get("series") or {}

    water = series.get("surface_water_annual") or {}
    writer.heading(f"{number}.1 Annual surface water (JRC, 1984–2021)", 2)
    if water.get("status") == "assessed":
        paths = series_figure(water, output_directory / "figure-trend-surface-water-annual")
        writer.image(paths["png"], 16, f"{water['title']}. {water['method']} Hollow points are flagged years.", max_height_cm=8)
        writer.para(_statistics_line(water) + ".")
        _caveats(writer, water)
        figures["figure_trend_surface_water_annual_png"] = (paths["png"], "image/png")
        figures["figure_trend_surface_water_annual_svg"] = (paths["svg"], "image/svg+xml")
    else:
        _not_available(writer, water)

    daily, dekadal = series.get("rainfall_daily") or {}, series.get("rainfall_dekadal") or {}
    anomaly = record.get("rainfall_anomaly") or {}
    writer.heading(f"{number}.2 Rainfall before the target date (CHIRPS)", 2)
    if daily.get("status") == "assessed" and dekadal.get("status") == "assessed":
        paths = rainfall_figure(daily, dekadal, anomaly, output_directory / "figure-trend-rainfall")
        writer.image(paths["png"], 16, f"{daily['title']}, and 10-day totals ending on the target's last day. "
                     f"{daily['method']}", max_height_cm=10)
        if anomaly.get("status") == "assessed":
            writer.table(["Window", "Total (mm)", "1991–2020 mean of the same window (mm)", "Anomaly"],
                         [[f"{anomaly['window_days']} days to {anomaly['last_day']}", _num(anomaly.get("total_mm"), 1),
                           _num(anomaly.get("climatology_mean_mm"), 1), anomaly.get("anomaly_text") or "—"]],
                         caption="Rainfall over the window compared with the 1991–2020 mean of the same calendar window.")
        _caveats(writer, daily)
        figures["figure_trend_rainfall_png"] = (paths["png"], "image/png")
        figures["figure_trend_rainfall_svg"] = (paths["svg"], "image/svg+xml")
    else:
        _not_available(writer, daily if daily.get("status") != "assessed" else dekadal)

    sar = series.get("sar_open_water") or {}
    writer.heading(f"{number}.3 SAR open water per Sentinel-1 pass", 2)
    if sar.get("status") == "assessed":
        paths = series_figure(sar, output_directory / "figure-trend-sar-open-water")
        window = sar.get("window") or {}
        capped = (f" {sar.get('passes_in_window')} passes fall in the window; the latest {sar.get('passes_used')} are used."
                  if sar.get("capped") else "")
        writer.image(paths["png"], 16, f"{sar['title']}, orbit {sar.get('orbit')}, {window.get('first_day')} to "
                     f"{window.get('last_day')}.{capped} {sar['method']}", max_height_cm=8)
        writer.para(_statistics_line(sar) + ".")
        _caveats(writer, sar)
        figures["figure_trend_sar_open_water_png"] = (paths["png"], "image/png")
        figures["figure_trend_sar_open_water_svg"] = (paths["svg"], "image/svg+xml")
    else:
        _not_available(writer, sar)

    writer.para("Sources: " + " ".join(sorted({s.get("source") for s in series.values() if s.get("source")})))
    return figures
