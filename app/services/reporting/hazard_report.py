"""Report section of the modelled flood hazard (Depth & Exposure module, plan item 1.6).

Written to the scientific report (PDF and Word) after the provenance summary, before the appendices, and only when the
run asked for the modelled hazard. It is context next to the observed flood map, never an accuracy measure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.firris.hazard_sources import GLOFAS_METHOD_REFERENCES
from app.services.reporting.hazard_figures import aep_figure, depth_return_period_figure

SECTION = "12. Modelled flood hazard (GloFAS v2.1, context)"
MAP_KEYS = ("modelled_flood_depth_rp10", "modelled_flood_depth_rp100", "modelled_flood_depth_rp500")
FIGURE_LABELS = {"modelled_hazard_depth_by_return_period": "Modelled flood hazard — depth by return period",
                 "modelled_hazard_aep": "Modelled flood hazard — AEP and probability of at least one occurrence"}


def _num(value, digits=2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def _pct(value) -> str:
    if value is None:
        return "—"
    return "> 99.9%" if value > 0.999 else f"{value * 100:.1f}%"


def is_hazard_map(key: str) -> bool:
    return key.startswith("modelled_flood_depth_")


def hazard_section(writer, output_directory: Path, record: dict[str, Any] | None, map_entries: dict[str, dict],
                   *, aoi: str | None = None) -> dict[str, tuple[Path, str]]:
    """Write section 12 and return its figure files (for the downloads list and the package)."""
    if not record:
        return {}
    writer.heading(SECTION)
    note = (record.get("method") or {}).get("note")
    status = record.get("status")
    if status != "assessed":
        writer.para(f"Modelled flood hazard: not available. {record.get('reason') or ''}".strip())
        writer.para(f"Source: {record.get('citation')}.")
        return {}
    writer.para(note)
    area = record["aoi"]
    rows = record["return_periods"]
    writer.para(f"Area {_num(area['area_km2'])} km², {_num(area['covered_pct'], 1)}% inside the GloFAS maps. Permanent water "
                f"({_num(record['permanent_water_km2'])} km², {_num(record['permanent_water_pct_of_aoi'], 1)}% of the area) is not "
                "flooding: it is excluded from the figures below and delivered as a separate layer. Including it, the wet share "
                f"would be {_num(rows[0]['including_permanent_water']['wet_pct_of_aoi'], 1)}% (1-in-{rows[0]['return_period_years']}) to "
                f"{_num(rows[-1]['including_permanent_water']['wet_pct_of_aoi'], 1)}% (1-in-{rows[-1]['return_period_years']})."
                + (f" Cells flagged as spurious depth ({_num(record['spurious_km2'])} km²) are excluded." if record.get("spurious_km2") else ""))
    has_observed = any(r.get("observed_extent") for r in rows)
    header = ["Return period (years)", "AEP", "Wet area, km² (% of area)", "Depth median / mean / p90 / max (m)"]
    if has_observed:
        header.append("Flood candidates of this run inside the zone")
    table = []
    for r in rows:
        d = r["depth_m"]
        line = [str(r["return_period_years"]), _pct(r["aep"]), f"{_num(r['wet_area_km2'])} ({_num(r['wet_pct_of_aoi'], 1)}%)",
                f"{_num(d['p50'])} / {_num(d['mean'])} / {_num(d['p90'])} / {_num(d['max'])}"]
        if has_observed:
            obs = (r.get("observed_extent") or {}).get("inside_pct")
            line.append("—" if obs is None else f"{obs:.1f}%")
        table.append(line)
    writer.table(header, table, caption="Modelled river-flood hazard by return period (wet cells: depth ≥ 0.1 m; area-weighted; "
                                       "permanent water excluded).")
    if has_observed:
        writer.para("The last column is the share of this run's observed flood-candidate pixels that fall inside each modelled "
                    "zone. It is context, not accuracy: the GloFAS maps are an undefended model of river floods of a given "
                    "return period, while the flood map is an observation of one date.")
    figures: dict[str, tuple[Path, str]] = {}
    depth = depth_return_period_figure(record, output_directory / "figure-modelled_hazard-depth_by_return_period",
                                       title="Modelled flood depth by return period (GloFAS v2.1, context)")
    writer.image(depth["png"], 16, "Modelled flood depth of the wet cells (median, mean, 90th percentile, maximum) by return "
                 f"period of the river discharge, with the wet share of {aoi or 'the area'} (bars, right axis); permanent water "
                 "excluded. GloFAS v2.1, undefended; the return period refers to the discharge.", max_height_cm=12)
    aep = aep_figure(record, output_directory / "figure-modelled_hazard-aep",
                     title="Return period, annual exceedance probability and the chance of at least one occurrence")
    writer.image(aep["png"], 16, "Left: annual exceedance probability AEP = 1/T of the T-year river discharge (Gumbel fit to "
                 "annual maxima). Right: probability of at least one occurrence in n years, P = 1 − (1 − 1/T)ⁿ, assuming "
                 "independent years.", max_height_cm=12)
    years = (record.get("occurrence") or {}).get("years") or []
    writer.table(["Return period (years)", "AEP", *[f"n = {n}" for n in years]],
                 [[str(row["return_period_years"]), _pct(row["aep"]),
                   *[_pct(row["probability_at_least_once"][str(n)]) for n in years]]
                  for row in record["occurrence"]["rows"]],
                 caption="Probability of at least one occurrence of the T-year river discharge in n years.")
    for key in MAP_KEYS:
        entry = map_entries.get(f"{key}_map_png")
        if entry:
            period = key.rsplit("rp", 1)[1]
            writer.image(output_directory / entry["path"], 16, f"Modelled flood depth, 1-in-{period}-year river discharge "
                         "(GloFAS v2.1, undefended, ~90 m). Permanent water is shown as no data.", max_height_cm=10)
    writer.para(f"Source: {record['citation']}. Method: " + "; ".join(GLOFAS_METHOD_REFERENCES) + ".")
    writer.para(f"Attribution: {record['attribution']} Licence: {record['licence']}")
    for name, paths in (("modelled_hazard_depth_by_return_period", depth), ("modelled_hazard_aep", aep)):
        figures[f"figure_{name}_png"] = (paths["png"], "image/png")
        figures[f"figure_{name}_svg"] = (paths["svg"], "image/svg+xml")
    return figures
