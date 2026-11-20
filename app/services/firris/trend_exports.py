"""Trend Analysis files: one CSV per series, the rainfall anomaly CSV and the record JSON (plan §5)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.platform.result_exports import artifact_entry
from app.services.reporting.report_builder import export_csv

FILE_NAMES = {"surface_water_annual": "trend-surface-water-annual.csv", "rainfall_daily": "trend-rainfall-daily.csv",
              "rainfall_dekadal": "trend-rainfall-10-day.csv", "sar_open_water": "trend-sar-open-water-per-pass.csv"}


def series_rows(series: dict[str, Any]) -> list[dict[str, Any]]:
    """The table of one series: time, value with units, flag, and the series' extra columns."""
    units = series.get("units", "")
    rows = []
    for point in series.get("points") or []:
        row = {"time": point["t"], f"value ({units})": point.get("value"), "flagged": bool(point.get("flagged")),
               "flag": point.get("flag") or ""}
        for column, label in (series.get("columns") or {}).items():
            value = point.get(column)
            row[label] = ", ".join(value) if isinstance(value, list) else value
        rows.append(row)
    return rows


def workbook_rows(record: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One long table for the workbook sheet "Trend analysis": every point of every series, with its source."""
    rows = []
    for key, series in ((record or {}).get("series") or {}).items():
        if series.get("status") != "assessed":
            rows.append({"series": series.get("title", key), "status": "not available", "note": series.get("reason")})
            continue
        summary = series.get("summary") or {}
        for point in series.get("points") or []:
            rows.append({"series": series["title"], "time": point["t"], "value": point.get("value"), "units": series["units"],
                         "flagged": bool(point.get("flagged")), "flag": point.get("flag") or "",
                         "statistics": summary.get("kind"), "source": series.get("source")})
    anomaly = (record or {}).get("rainfall_anomaly") or {}
    if anomaly.get("status") == "assessed":
        rows.append({"series": "Rainfall anomaly", "time": anomaly["last_day"], "value": anomaly.get("anomaly_percent"),
                     "units": "% of the 1991–2020 mean", "flagged": anomaly.get("total_mm") is None,
                     "flag": anomaly.get("anomaly_text"), "statistics": f"{anomaly['window_days']}-day window",
                     "source": anomaly.get("source")})
    return rows or [{"series": None, "status": "not available"}]


def trend_exports(output_directory: Path, record: dict[str, Any], *, result_version: int) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    path = output_directory / "trend-analysis.json"
    path.write_text(json.dumps(record, indent=2, default=float), encoding="utf-8")
    entries["trend_analysis_json"] = artifact_entry(
        path, label="Trend analysis: record (series, rules, sources)", media_type="application/json", artifact_type="report",
        result_version=result_version, role="export", delivery_type="metadata_json", format_name="json")
    for key, name in FILE_NAMES.items():
        series = (record.get("series") or {}).get(key) or {}
        if series.get("status") != "assessed":
            continue
        csv_path = output_directory / name
        export_csv(pd.DataFrame(series_rows(series)), str(csv_path))
        entries[f"trend_{key}_csv"] = artifact_entry(
            csv_path, label=f"Trend analysis: {series['title']} (CSV)", media_type="text/csv", artifact_type="report",
            result_version=result_version, role="export", delivery_type="csv", format_name="csv")
    anomaly = record.get("rainfall_anomaly") or {}
    if anomaly.get("status") == "assessed":
        csv_path = output_directory / "trend-rainfall-anomaly.csv"
        export_csv(pd.DataFrame([{k: anomaly.get(k) for k in ("last_day", "window_days", "total_mm", "climatology_mean_mm",
                                                              "anomaly_percent", "anomaly_text", "missing_days")}]), str(csv_path))
        entries["trend_rainfall_anomaly_csv"] = artifact_entry(
            csv_path, label="Trend analysis: rainfall anomaly (CSV)", media_type="text/csv", artifact_type="report",
            result_version=result_version, role="export", delivery_type="csv", format_name="csv")
    return entries
