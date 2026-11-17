"""Report section of the estimated exposure (Depth & Exposure module, plan item 2.5).

Written after the modelled hazard (both after the accuracy assessment), only when the run asked for the exposure. Every number is an estimate
with its version, year, threshold and method; the section never speaks of people affected.
"""
from __future__ import annotations

from pathlib import Path

from app.services.firris.hazard_sources import GLOFAS_PRODUCED_WORK_NOTICE
from typing import Any

SECTION = "Estimated exposure (WorldPop, Open Buildings)"
MAP_KEYS = ("exposed_population_observed_extent", "exposed_population_rp100")


def _int(value) -> str:
    return "—" if value is None else f"{round(value):,}"


def _km2(value) -> str:
    return "—" if value is None else f"{value:,.2f}"


def is_exposure_map(key: str) -> bool:
    return key.startswith("exposed_population_")


def exposure_section(writer, output_directory: Path, record: dict[str, Any] | None, map_entries: dict[str, dict], *,
                     number: int = 11) -> None:
    if not record:
        return
    writer.heading(f"{number}. {SECTION}")
    if record.get("status") != "assessed":
        writer.para(f"Estimated exposure: not available. {record.get('reason') or ''}".strip())
        return
    population, buildings = record["population"], record["buildings"]
    year = population["year"]
    status = population["year_status"]
    writer.para(record["wording"])
    writer.para(f"People: WorldPop R2025A, {year}. This is a {status['text']}." +
                (f" The analysis target year was {population['requested_year']}; the nearest WorldPop year is used."
                 if population["requested_year"] != year else "") +
                " Counts are area-weighted: the people of each 100 m cell × the share of the cell inside the extent. "
                + population["release_caveat"])
    writer.para(f"Buildings: Google Open Buildings {buildings['version']}, counted when the building's centroid lies inside the "
                f"extent, at detection confidence ≥ {buildings['primary_threshold']:.2f} ({buildings['threshold_note']}); the count at "
                f"≥ {buildings['sensitivity_threshold']:.2f} is shown as a sensitivity. Exact counts, no sampling. "
                f"{buildings['limitation']} Spot-check: {buildings['spot_check']}.")
    writer.para(record["permanent_water"])
    rows = record["rows"]
    table = []
    for row in rows:
        b = row["buildings"]
        buildings_text = (f"{_int(b['0.75']['count'])} ({_int(b['0.65']['count'])})" if b.get("status") == "counted"
                          else f"not available: {b.get('reason')}")
        table.append([row["label"], _km2(row["area_km2"]), _int(row["people"]), buildings_text])
    writer.table(["Extent", "Area (km²)", f"People, WorldPop {year} (estimate)",
                  f"Buildings, confidence ≥ {buildings['primary_threshold']:.2f} (≥ {buildings['sensitivity_threshold']:.2f})"],
                 table, caption=f"Estimated exposure by extent: WorldPop R2025A {year} ({status['status']}), area-weighted; Open Buildings "
                                f"{buildings['version']}, centroid inside the extent; GloFAS permanent water excluded from the modelled zones only.")
    observed = next((r for r in rows if r["extent"] == "observed_extent"), None)
    caveat, cluster = record.get("observed_extent_caveat"), record.get("observed_cluster") or {}
    if observed and caveat:  # beside the observed-extent figures (owner, 2026-11-17)
        writer.para(f"Observed flood candidates: {caveat['text']} {caveat['built_up_note']}"
                    + (f" {cluster['text']}" if cluster.get("text") else ""))
    if observed:
        masked = observed.get("sensitivity_glofas_permanent_water_masked")
        writer.para((f"Sensitivity only: masking the observed flood candidates with the coarser GloFAS permanent water (~90 m) "
                     f"would give {_km2(masked['area_km2'])} km² and {_int(masked['people'])} people. " if masked else "")
                    + "Counting every 100 m cell that touches the observed extent instead of area-weighting would give "
                    f"{_int(observed['people_cells_touching'])} people; that overstates exposure and is not used.")
    for key in MAP_KEYS:
        entry = map_entries.get(f"{key}_map_png")
        if entry:
            observed_map = key.endswith("observed_extent")
            what = "the observed flood candidates of this run" if observed_map else "the modelled 1-in-100-year zone"
            writer.image(output_directory / entry["path"], 16, f"Estimated people per ~100 m cell inside {what} (WorldPop R2025A {year}, "
                         "area-weighted; an estimate, not people affected)."
                         + (f" {caveat['text']}" if observed_map and caveat else ""), max_height_cm=10)
    points = record.get("building_points") or {}
    if points.get("status") == "not_delivered":
        writer.para(f"Building layer: not delivered. {points.get('reason')}")
    writer.para(f"Sources: {population['citation']} Licence: {population['licence']}. {buildings['citation']}. "
                f"Licence: {buildings['licence']}. Return-period zones: {GLOFAS_PRODUCED_WORK_NOTICE}.")
