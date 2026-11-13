"""Read-time result overview for FIRRIS flood results (plan item 2.3).

Computed only from what the result already stores (summary and provenance); it adds no
new science. Anything a result did not record is reported as "not recorded", never guessed.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.reporting.data_sources import SOURCES, credit, datasets_with_companions

DEFAULT_MINIMUM_COVERAGE_PCT = 70.0  # pipeline default when a result did not record its gate value
DEFAULT_MAX_CLOUD_PCT = 20.0
INDEPENDENT_THRESHOLD = "compliant Sentinel-2 at both dates; ≥ 50 eligible pixels per class"
OPTICAL_BANDS = {"source_mndwi_target", "source_mndwi_baseline", "optical_reference"}
SCENE_COLLECTIONS = {
    "COPERNICUS/S1_GRD": ("sentinel_1_target", "sentinel_1_baseline"),
    "COPERNICUS/S2_SR_HARMONIZED": ("sentinel_2_target", "sentinel_2_baseline"),
    "UCSB-CHG/CHIRPS/DAILY": ("chirps_target",),
}
STATUS_TEXT = {"not_assessable": "not assessable", "insufficient_reference_samples": "insufficient reference samples",
               "not_performed": "not performed", "assessed": "assessed"}


def _gate(name: str, threshold: str, observed: str | None, status: str) -> dict[str, Any]:
    return {"name": name, "threshold": threshold, "observed": observed, "status": status}


def _scenes(quality: dict, *keys: str) -> list[dict]:
    collections = quality.get("per_collection") or {}
    return [scene for key in keys for scene in (collections.get(key) or {}).get("scenes", []) if isinstance(scene, dict)]


def _period(provenance: dict, key: str) -> str | None:
    period = provenance.get(key) or {}
    return f"{period['start']} to {period['end']}" if period.get("start") and period.get("end") else None


def _headline(area: dict, provenance: dict) -> dict[str, Any]:
    flooded, share, valid = area.get("flooded_area_km2"), area.get("flooded_percent_of_valid"), area.get("valid_area_km2")
    target, baseline = _period(provenance, "target_period"), _period(provenance, "baseline_period")
    dates = (f"for target {target}, compared with baseline {baseline} (end dates exclusive)" if target and baseline
             else "(target and baseline dates not recorded)")
    text = (f"Model-classified flood candidates cover {flooded:.2f} km² ({share:.2f}% of the {valid:.2f} km² valid analysed area) {dates}. "
            "Flood candidates are a model classification trained on SAR screening labels, not confirmed flood observations.")
    return {"text": text, "flood_candidate_area_km2": flooded, "percent_of_valid": share, "valid_area_km2": valid,
            "target_period": target, "baseline_period": baseline}


def _area_accounting(area: dict, quality: dict, provenance: dict) -> dict[str, Any]:
    aoi_cells, valid_cells = quality.get("aoi_cells"), quality.get("valid_aoi_cells", area.get("valid_cells"))
    mean_cell_km2 = area["valid_area_km2"] / valid_cells if valid_cells else None
    aoi_km2 = mean_cell_km2 * aoi_cells if mean_cell_km2 and aoi_cells else None
    bands = provenance.get("band_identity") or []
    admission = quality.get("admission_bands")
    missing = []
    for index, cells in sorted((quality.get("missing_cells_by_band") or {}).items(), key=lambda item: int(item[0])):
        name = bands[int(index)] if int(index) < len(bands) else f"band {index}"
        missing.append({"band": name, "cells": int(cells), "pct_of_aoi": cells / aoi_cells * 100 if aoi_cells else None,
                        "affects_admission": name not in OPTICAL_BANDS if admission is None else name in admission})
    return {
        "aoi_cells": aoi_cells, "valid_cells": valid_cells,
        "excluded_cells": aoi_cells - valid_cells if aoi_cells is not None and valid_cells is not None else None,
        "valid_area_km2": area.get("valid_area_km2"), "aoi_area_km2_estimate": aoi_km2,
        "excluded_area_km2_estimate": aoi_km2 - area["valid_area_km2"] if aoi_km2 is not None else None,
        "valid_pct_of_aoi": quality.get("valid_pixel_coverage_pct"),
        "flood_candidate_area_km2": area.get("flooded_area_km2"), "flood_candidate_pct_of_valid": area.get("flooded_percent_of_valid"),
        "flood_candidate_pct_of_aoi": area["flooded_area_km2"] / aoi_km2 * 100 if aoi_km2 else None,
        "missing_cells_by_band": missing,
        "method_note": ("AOI and excluded areas are estimated as cell counts × mean valid-cell area; "
                        "a cell can be missing in several bands, so band counts overlap and do not add up."),
    }


def _quality_gates(summary: dict, quality: dict, provenance: dict) -> list[dict[str, Any]]:
    gates = []
    minimum = quality.get("minimum_valid_coverage_pct", DEFAULT_MINIMUM_COVERAGE_PCT)
    coverage = quality.get("valid_pixel_coverage_pct")
    gates.append(_gate("Valid pixel coverage", f"≥ {minimum:g}%", None if coverage is None else f"{coverage:.2f}%",
                       "not_recorded" if coverage is None else ("pass" if coverage >= minimum else "fail")))
    optical = _scenes(quality, "sentinel_2_target", "sentinel_2_baseline")
    max_cloud = quality.get("max_cloud_pct", DEFAULT_MAX_CLOUD_PCT)
    clouds = [scene["cloud_pct"] for scene in optical if isinstance(scene.get("cloud_pct"), (int, float))]
    gates.append(_gate("Sentinel-2 cloud cover", f"≤ {max_cloud:g}% per scene",
                       f"max {max(clouds):.1f}% over {len(clouds)} scenes" if clouds else None,
                       ("pass" if max(clouds) <= max_cloud else "fail") if clouds else "not_recorded"))
    degraded = [scene["degraded_msi_pct"] for scene in optical if isinstance(scene.get("degraded_msi_pct"), (int, float))]
    # Runs since client decision D6 record their scene threshold; earlier results ran at 0%.
    degraded_limit = float(quality.get("degraded_msi_max_pct", 0.0))
    degraded_threshold = f"≤ {degraded_limit:g}% per scene" if degraded_limit else "= 0%"
    gates.append(_gate("Sentinel-2 degraded MSI", degraded_threshold, f"max {max(degraded):.2f}% over {len(degraded)} scenes" if degraded else None,
                       ("pass" if max(degraded) <= degraded_limit else "fail") if degraded else "not_recorded"))
    orbits = [sorted({scene["relative_orbit"] for scene in _scenes(quality, key) if "relative_orbit" in scene})
              for key in ("sentinel_1_target", "sentinel_1_baseline")]
    if all(orbits):
        gates.append(_gate("Sentinel-1 relative orbit match", "one orbit, same in both periods",
                           f"target {', '.join(map(str, orbits[0]))}; baseline {', '.join(map(str, orbits[1]))}",
                           "pass" if orbits[0] == orbits[1] and len(orbits[0]) == 1 else "fail"))
    else:
        gates.append(_gate("Sentinel-1 relative orbit match", "one orbit, same in both periods", None, "not_recorded"))
    sampling = provenance.get("sampling") or {}
    counts, minimum_class = sampling.get("class_counts"), sampling.get("minimum_per_class")
    if counts and minimum_class is not None:
        gates.append(_gate("Class support", f"≥ {minimum_class} samples per class",
                           "; ".join(f"class {label}: {value}" for label, value in sorted(counts.items())),
                           "pass" if all(value >= minimum_class for value in counts.values()) else "fail"))
    else:
        gates.append(_gate("Class support", "minimum samples per class", None, "not_recorded"))
    rainfall = (quality.get("per_collection") or {}).get("chirps_target") or {}
    target = provenance.get("target_period") or {}
    if rainfall.get("scenes") is not None and target.get("start") and target.get("end"):
        expected = (date.fromisoformat(target["end"]) - date.fromisoformat(target["start"])).days
        received = len({scene.get("acquired_at") for scene in rainfall["scenes"]})
        gates.append(_gate("Daily rainfall completeness", "every day of the target window",
                           f"{received} of {expected} days", "pass" if received == expected else "fail"))
    else:
        gates.append(_gate("Daily rainfall completeness", "every day of the target window", None, "not_recorded"))
    independent = summary.get("independent_accuracy")
    if not independent:
        gates.append(_gate("Independent reference", INDEPENDENT_THRESHOLD, None, "not_recorded"))
    elif independent.get("status") == "assessed":
        gates.append(_gate("Independent reference", INDEPENDENT_THRESHOLD, "assessed (census of eligible pixels)", "pass"))
    else:
        text = STATUS_TEXT.get(independent.get("status"), str(independent.get("status")))
        reason = f": {independent['reason']}" if independent.get("reason") else ""
        gates.append(_gate("Independent reference", INDEPENDENT_THRESHOLD, f"{text}{reason}", "not_applicable"))
    return gates


def _data_sources(quality: dict, provenance: dict) -> list[dict[str, Any]]:
    sources = []
    for dataset in datasets_with_companions(provenance):
        role, resolution, _ = SOURCES.get(dataset, ("Source dataset", "not recorded", dataset))
        dates = sorted({scene["acquired_at"] for scene in _scenes(quality, *SCENE_COLLECTIONS.get(dataset, ())) if scene.get("acquired_at")})
        sources.append({"dataset": dataset, "role": role, "resolution": resolution, "scene_dates": dates,
                        "credit": credit(dataset, sorted({value[:4] for value in dates}))})
    return sources


def _limitations(summary: dict) -> list[str]:
    specific = []
    independent = summary.get("independent_accuracy") or {}
    if independent.get("status") in {"not_assessable", "insufficient_reference_samples"}:
        reason = f" — {independent['reason']}" if independent.get("reason") else ""
        specific.append(f"Independent accuracy: {STATUS_TEXT[independent['status']]}{reason}")
    general = list((summary.get("validation_dashboard") or {}).get("limitations") or [])
    return specific + [item for item in general if item not in specific]


def build_result_overview(result) -> dict[str, Any] | None:
    summary = result.summary if isinstance(result.summary, dict) else {}
    provenance = result.provenance if isinstance(result.provenance, dict) else {}
    products = summary.get("products")
    extent = products.get("flood_extent") if isinstance(products, dict) else None
    area = extent.get("area_statistics") if isinstance(extent, dict) else None
    if (result.engine_key != "firris" or not isinstance(area, dict)
            or not {"flooded_area_km2", "flooded_percent_of_valid", "valid_area_km2"} <= set(area)):
        return None
    quality = summary.get("quality") or {}
    return {"headline": _headline(area, provenance), "area_accounting": _area_accounting(area, quality, provenance),
            "quality_gates": _quality_gates(summary, quality, provenance), "data_sources": _data_sources(quality, provenance),
            "limitations": _limitations(summary)}
