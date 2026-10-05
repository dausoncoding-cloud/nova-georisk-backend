"""Descriptive delivery facts from actual artifacts; never synthesize truth."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.warp import transform_bounds

from app.schemas.result_delivery import ResultAnalytics, ResultInterpretation
from app.services.firris.area_statistics import raster_area_statistics
from app.services.maps.export import RasterSpec

LIMITATIONS = [
    "Delivered-cell accounting is not cadastral/ground area or independently validated flood accuracy.",
    "Source approval and model-internal validation do not establish calibration, causality, AEP or forecasting skill.",
    "Histograms describe observed delivered values; their display bins are not scientific class thresholds.",
    "Temporal points are emitted only for an explicitly comparable observed before/after product; no trend is inferred from Result creation time or version.",
]


def verified_artifact(directory: Path, entry: dict) -> Path:
    root = directory.resolve()
    path = (root / entry["path"]).resolve(strict=True)
    path.relative_to(root)
    if not path.is_file():
        raise ValueError("Delivery source is not a file")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != entry.get("checksum_sha256") or path.stat().st_size != entry.get("file_size_bytes"):
        raise ValueError("Delivery source checksum differs")
    return path


def display_bounds(crs: str, bounds) -> dict:
    if isinstance(bounds, dict):
        bounds = [bounds[key] for key in ("west", "south", "east", "north")]
    if len(bounds) != 4 or not np.isfinite(bounds).all() or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise ValueError("Layer bounds are invalid")
    west, south, east, north = transform_bounds(crs, "EPSG:4326", *bounds, densify_pts=21)
    if not np.isfinite([west, south, east, north]).all() or not -180 <= west < east <= 180 or not -90 <= south < north <= 90:
        raise ValueError("Layer cannot be represented by one WGS84 display envelope")
    return dict(west=west, south=south, east=east, north=north)


def _legend(entry):
    value = (entry.get("gis_metadata") or {}).get("legend") or (entry.get("layer") or {}).get("legend") or []
    return value.get("entries", []) if isinstance(value, dict) else value


def quantitative_delivery(directory: Path, entries: dict, summary: dict, provenance: dict) -> dict:
    rows, series, seen = [], [], set()
    candidates = sorted(entries.items(), key=lambda pair: (pair[1].get("format") != "cog", pair[0]))
    for name, entry in candidates:
        product = entry.get("product_key") or name
        if entry.get("role") != "product" or entry.get("artifact_type") != "raster" or product in seen:
            continue
        if entry.get("format") not in {"cog", "geotiff", "tif"}:
            continue
        meta = entry.get("gis_metadata") or {}
        path = verified_artifact(directory, entry)
        with rasterio.open(path) as raster:
            if raster.count != 1 or raster.crs is None or CRS.from_user_input(meta["crs"]) != raster.crs or raster.nodata != meta.get("nodata"):
                raise ValueError("Quantitative delivery CRS/bands/nodata differ from declared source")
            values = raster.read(1, masked=True)
            valid = ~np.ma.getmaskarray(values)
            if not valid.any() or not np.isfinite(values.data[valid]).all():
                raise ValueError("Quantitative source has no finite valid cells")
            spec = RasterSpec(raster.transform, raster.crs.to_epsg())
            if spec.crs_epsg is None:
                raise ValueError("Quantitative delivery requires an EPSG source CRS")
            stats = raster_area_statistics(values.data, spec, nodata_mask=valid)
            seen.add(product)
            bands = _legend(entry)
            # Float rasters remain continuous even when a display legend exists.
            # Explicit categorical integer code legends add zero-cell classes.
            classification_basis = "delivered integer class codes; no continuous-score threshold invented"
            display_labels = None
            if "class_areas" not in stats and bands and not any("value" in band for band in bands):
                from app.services.maps.cartography import MAP_KEYS, _class_codes, _legend as normalize_legend
                if product in MAP_KEYS:
                    codes = np.zeros(values.shape, dtype="int16")
                    codes[valid] = _class_codes(values.data[valid], normalize_legend(bands), product)
                    categorical = raster_area_statistics(codes, spec, nodata_mask=valid)
                    stats["class_areas"] = categorical["class_areas"]
                    display_labels = {index: str(band["label"]) for index, band in enumerate(bands, 1)}
                    classification_basis = "recorded display legend via existing classifier; presentation areas, not new scientific or safety thresholds"
            if "class_areas" in stats:
                labels = {int(band["value"]): str(band["label"]) for band in bands if "value" in band}
                if display_labels is not None:
                    labels = display_labels
                if product == "flood_extent":
                    labels = {0: "not flooded", 1: "flooded"}
                by_class = {row["class_value"]: row for row in stats["class_areas"]}
                for value in sorted(set(labels) | set(by_class)):
                    row = by_class.get(value, dict(class_value=value, cells=0, area_m2=0., area_ha=0., area_km2=0., percent_of_valid=0.))
                    rows.append(dict(product_key=product, label=labels.get(value, str(value)), **row,
                        denominator_area_m2=stats["valid_area_m2"], area_method=stats["method"],
                        classification_basis=classification_basis, evidence_ref="artifacts." + name))
                series.append(dict(product_key=product, kind="class_area", units="ha",
                    points=[dict(label=row["label"], value=row["area_ha"]) for row in rows if row["product_key"] == product],
                    basis=classification_basis + "; valid-cell denominator", evidence_refs=["artifacts." + name]))
            if not np.issubdtype(values.dtype, np.integer):
                counts, edges = np.histogram(values.compressed(), bins=20)
                series.append(dict(product_key=product, kind="histogram", units=meta.get("units") or "not supplied",
                    points=[dict(lower=float(low), upper=float(high), count=int(count)) for low, high, count in zip(edges[:-1], edges[1:], counts)],
                    basis="20 display-only equal-width bins over finite valid delivered values; last bin right-inclusive", evidence_refs=["artifacts." + name]))
    change = summary.get("change_statistics")
    comparison = provenance.get("comparison")
    if change is not None:
        if not isinstance(comparison, dict) or not comparison.get("observation_definition"):
            raise ValueError("Temporal evidence lacks the fixed comparison definition")
        stamps = [comparison["before_timestamp"], comparison["after_timestamp"]]
        if datetime.fromisoformat(stamps[0]) >= datetime.fromisoformat(stamps[1]):
            raise ValueError("Temporal evidence timestamps are incompatible")
        areas = [change["before_inundated_area_m2"], change["after_inundated_area_m2"]]
        if not np.isfinite(areas).all() or min(areas) < 0:
            raise ValueError("Temporal evidence areas are invalid")
        series.append(dict(product_key="flood_change", kind="observed_time_series", units="m2",
            points=[dict(timestamp=stamp, value=float(area)) for stamp, area in zip(stamps, areas)],
            basis="two comparable observed instants under one sourced binary definition; not a forecast or fitted trend",
            evidence_refs=["summary.change_statistics", "provenance.comparison"]))
    return ResultAnalytics(class_areas=rows, series=series, limitations=LIMITATIONS).model_dump(mode="json")


def interpret_evidence(analytics: dict, summary: dict, provenance: dict) -> dict:
    findings = []
    for row in analytics["class_areas"]:
        findings.append(dict(text=f"Delivered {row['product_key']} class {row['class_value']} ({row['label']}) covers {row['area_ha']:.6g} ha ({row['percent_of_valid']:.6g}% of valid delivered area).",
            evidence_refs=[row["evidence_ref"], "analytics.class_areas"]))
    for item in analytics["series"]:
        if item["kind"] == "histogram":
            findings.append(dict(text=f"The delivered {item['product_key']} histogram accounts for {sum(point['count'] for point in item['points'])} finite valid cells in display-only bins.", evidence_refs=item["evidence_refs"]))
    change = summary.get("change_statistics")
    if change:
        findings.append(dict(text=f"Observed net inundated-area change is {change['net_inundated_change_m2']:.6g} m². Relative change uses before-inundated area and is undefined when that area is zero; these observations do not establish cause or a future trend.",
            evidence_refs=["summary.change_statistics", "provenance.comparison"]))
    if not findings:
        findings.append(dict(text="This Result has no delivered georeferenced raster class-area evidence; no spatial area or temporal trend is inferred from sample-only calculations.", evidence_refs=["summary", "artifacts"]))
    recommendations = [dict(text="Review recorded source identity, licensing, QA and uncertainty before operational use, and obtain independent observations for validation.", evidence_refs=["provenance"]),
        dict(text="Use each delivered product's recorded units, grid and denominator; do not interpret a conditional classifier score as annual exceedance probability or a safety threshold.", evidence_refs=["analytics.limitations", "artifacts"])]
    return ResultInterpretation(findings=findings, recommendations=recommendations,
        limitations=LIMITATIONS + ["Automatic text uses deterministic evidence rules; no generative model, external knowledge, causal explanation or operational safety advice is asserted."]).model_dump(mode="json")
