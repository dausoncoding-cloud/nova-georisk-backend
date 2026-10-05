"""Approved spatial assets inside a reviewed Hazard-index zone -> FIRRIS E.

Counts are estimates in a selected *Hazard index class*, not observed flooded
people or damage. The approved entropy formula is called without alteration.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from pyproj import CRS, Geod, Transformer
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject
from shapely.geometry import box, mapping, shape
from shapely.ops import transform as transform_shape, unary_union
from shapely.strtree import STRtree

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.firas.exposure import DEFAULT_EXPOSURE_DIRECTIONS, compute_exposure_index
from app.services.maps.export import RasterSpec, write_cog
from app.services.reporting.report_builder import IndexSummary, ReportContext, export_csv, generate_excel_report, generate_pdf_report
from app.services.source_data.bindings import ResolvedBindings
from app.services.source_data.readiness import SourceNotReady


_ZONE_MIN = {"moderate": 0.4, "high": 0.6, "extreme": 0.8}
_NODATA = -9999.0
_LEGEND = [
    {"label": "Very Low", "min": 0.0, "max": 0.2, "color": "#0B3C5D"},
    {"label": "Low", "min": 0.2, "max": 0.4, "color": "#00B4D8"},
    {"label": "Moderate", "min": 0.4, "max": 0.6, "color": "#F9C74F"},
    {"label": "High", "min": 0.6, "max": 0.8, "color": "#F8961E"},
    {"label": "Very High", "min": 0.8, "max": 1.0, "color": "#D00000"},
]
_RAW_UNITS = {
    "population_density": "people/km2", "building_density": "buildings/km2",
    "road_network_density": "km/km2", "critical_infrastructure_density": "assets/km2",
    "cropland_density": "cropland_fraction", "industrial_commercial_density": "assets/km2",
    "livestock_density": "animals/km2",
}
_GEOD = Geod(ellps="WGS84")


def _length_m(geometry, back: Transformer) -> float:
    if geometry.is_empty:
        return 0.0
    if geometry.geom_type in {"LineString", "MultiLineString"}:
        return float(_GEOD.geometry_length(transform_shape(back.transform, geometry)))
    return sum(_length_m(part, back) for part in getattr(geometry, "geoms", ()))


def _average_raster(source, grid, zone_mask: np.ndarray) -> np.ndarray:
    """Area-average an observed density/fraction; never fabricate absent cells."""
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    with MemoryFile(source.data) as memory, memory.open() as raster:
        if raster.crs is None or raster.crs.to_string() != source.manifest.crs or raster.nodata != source.manifest.nodata:
            raise SourceNotReady("Exposure raster metadata differs from approved manifest")
        destination = np.full(zone_mask.shape, np.nan, dtype="float64")
        reproject(source=rasterio.band(raster, 1), destination=destination,
                  src_transform=raster.transform, src_crs=raster.crs, src_nodata=raster.nodata,
                  dst_transform=transform, dst_crs=grid.crs, dst_nodata=np.nan,
                  resampling=Resampling.average)
    if not np.isfinite(destination[zone_mask]).all():
        raise SourceNotReady("Exposure raster has unobserved cells inside the Hazard zone")
    if (destination[zone_mask] < 0).any():
        raise SourceNotReady("Exposure density/fraction contains negative values")
    if source.manifest.category == "cropland_fraction" and (destination[zone_mask] > 1).any():
        raise SourceNotReady("Cropland fraction exceeds one")
    return destination[zone_mask]


def _vector_inventory(source, projected_crs: str, aoi, cells, *, kind: str):
    """Clip reviewed features, count assets once, allocate road length by cell."""
    transformer = Transformer.from_crs("EPSG:4326", projected_crs, always_xy=True)
    back = Transformer.from_crs(projected_crs, "EPSG:4326", always_xy=True)
    features = json.loads(source.data)["features"]
    zone_index = STRtree(cells)
    seen = set()
    per_cell = np.zeros(len(cells), dtype=float)
    counts: dict[str, int] = {}
    selected = []
    total_length_m = 0.0
    for feature in features:
        properties = feature["properties"]
        asset_id = properties["asset_id"]
        if asset_id in seen:
            raise SourceNotReady(f"Duplicate {kind} asset identifier")
        seen.add(asset_id)
        geometry = transform_shape(transformer.transform, shape(feature["geometry"]))
        if geometry.is_empty or not geometry.is_valid:
            raise SourceNotReady(f"Invalid {kind} asset geometry")
        clipped = geometry.intersection(aoi)
        if clipped.is_empty:
            continue
        intersections = [(int(index), clipped.intersection(cells[int(index)]))
                         for index in zone_index.query(clipped)]
        intersections = [(index, part) for index, part in intersections if not part.is_empty]
        if kind == "roads":
            # A road on a shared cell edge belongs to one cell, not both.
            remaining = clipped
            unique_segments = []
            for index, _ in sorted(intersections, key=lambda item: item[0]):
                segment = remaining.intersection(cells[index])
                if _length_m(segment, back) > 0:
                    unique_segments.append((index, segment))
                    remaining = remaining.difference(segment)
            intersections = unique_segments
        if kind != "roads" and geometry.geom_type in {"Polygon", "MultiPolygon"}:
            intersections = [(index, part) for index, part in intersections
                             if part.area > max(cells[index].area * 1e-9, 1e-8)]
        if not intersections:
            continue
        zone_part = unary_union([part for _, part in intersections])
        if kind == "roads":
            length = 0.0
            for index, part in intersections:
                segment_length_m = _length_m(part, back)
                per_cell[index] += segment_length_m
                length += segment_length_m
            if length <= 0:
                continue
            total_length_m += length
            asset_type = properties["road_class"].strip().lower()
        else:
            asset_type = (properties["building_use"] if kind == "buildings" else properties["asset_type"]).strip().lower()
            if kind == "economic_assets" and asset_type not in {"industrial", "commercial"}:
                raise SourceNotReady("Economic source contains an undeclared non-industrial/commercial asset")
            rank = lambda item: item[1].area if item[1].area > 0 else 1.0 if item[1].geom_type == "Point" else 0.0
            chosen = max(intersections, key=rank)[0]
            per_cell[chosen] += 1
            counts[asset_type] = counts.get(asset_type, 0) + 1
        selected.append({"type": "Feature", "geometry": mapping(transform_shape(back.transform, zone_part)),
                         "properties": {"asset_id": asset_id, "source_category": kind,
                                        "asset_type": asset_type, "hazard_zone_intersection": True}})
    return per_cell, counts, total_length_m, selected


def _write_preview(path: Path, raster: np.ndarray, mask: np.ndarray) -> None:
    colors = np.array([[int(band["color"][offset:offset + 2], 16) for offset in (1, 3, 5)]
                       for band in _LEGEND], dtype=np.uint8)
    classes = np.searchsorted([0.2, 0.4, 0.6, 0.8], raster, side="left")
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[..., :3][mask] = colors[classes[mask]]
    rgba[..., 3][mask] = 255
    Image.fromarray(rgba, mode="RGBA").save(path)


def execute_exposure_module(bindings: ResolvedBindings, aoi_geometry: dict, output_directory: Path,
                            result_version: int, *, task_id: str = "") -> EngineExecutionOutput:
    request = bindings.request
    if request.module != "exposure" or request.target_grid is None or request.exposure_options is None or "hazard" not in bindings.upstream:
        raise SourceNotReady("A validated Exposure binding and protected Hazard Result are required")
    grid = request.target_grid
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    aoi = transform_shape(Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True).transform,
                          shape(aoi_geometry))
    aoi_mask = geometry_mask([mapping(aoi)], out_shape=(grid.height, grid.width),
                             transform=transform, invert=True)
    with MemoryFile(bindings.upstream["hazard"].raster_bytes) as memory, memory.open() as hazard_source:
        hazard = hazard_source.read(1, masked=True)
        valid_hazard = ~np.ma.getmaskarray(hazard)
        hazard_values = np.asarray(hazard.data, dtype=float)
    if not np.all(valid_hazard[aoi_mask]):
        raise SourceNotReady("Upstream Hazard Result does not cover every AOI cell")
    threshold = _ZONE_MIN[request.exposure_options.hazard_min_level]
    # Classification bands include the upper bound in the *lower* class.
    zone_mask = aoi_mask & valid_hazard & (hazard_values > threshold)
    if int(zone_mask.sum()) < 2:
        raise SourceNotReady("Selected Hazard index zone has fewer than two cells for entropy weighting")
    rows, cols = np.nonzero(zone_mask)
    cells = []
    areas_km2 = []
    back = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    for row, col in zip(rows, cols):
        west, north = transform * (int(col), int(row))
        east, south = transform * (int(col) + 1, int(row) + 1)
        cell = box(west, south, east, north).intersection(aoi)
        if cell.is_empty or cell.area <= 0:
            raise SourceNotReady("Hazard zone has a cell without measurable AOI area")
        cells.append(cell)
        geodesic_area_m2, _ = _GEOD.geometry_area_perimeter(transform_shape(back.transform, cell))
        if not np.isfinite(geodesic_area_m2) or abs(geodesic_area_m2) <= 0:
            raise SourceNotReady("Hazard zone cell has invalid geodesic area")
        areas_km2.append(abs(geodesic_area_m2) / 1_000_000)
    areas = np.asarray(areas_km2)
    population = _average_raster(bindings.sources["population"], grid, zone_mask)
    cropland = _average_raster(bindings.sources["cropland"], grid, zone_mask)
    livestock = _average_raster(bindings.sources["livestock"], grid, zone_mask)
    allocations, counts, road_lengths, vectors = {}, {}, {}, []
    for role in ("buildings", "roads", "critical_infrastructure", "economic_assets"):
        if role not in bindings.sources:
            continue
        allocation, by_type, length_m, features = _vector_inventory(
            bindings.sources[role], grid.crs, aoi, cells, kind=role)
        allocations[role], counts[role], road_lengths[role] = allocation, by_type, length_m
        vectors.extend(features)
    frame = pd.DataFrame({
        "population_density": population,
        "building_density": allocations["buildings"] / areas,
        "road_network_density": allocations["roads"] / 1000 / areas,
        "critical_infrastructure_density": allocations["critical_infrastructure"] / areas,
        "cropland_density": cropland,
        "livestock_density": livestock,
    })
    if "economic_assets" in allocations:
        frame["industrial_commercial_density"] = allocations["economic_assets"] / areas
    if not np.isfinite(frame.to_numpy()).all() or (frame.to_numpy() < 0).any():
        raise SourceNotReady("Exposure indicators are missing or invalid")
    if all(frame[key].nunique() == 1 for key in frame):
        raise SourceNotReady("All Exposure indicators are constant; informative weights cannot be derived")
    computed = compute_exposure_index(frame)
    if (not np.isfinite(computed.scores.to_numpy()).all()
            or not np.isclose(sum(computed.weights.values()), 1.0)
            or any(weight < -1e-9 for weight in computed.weights.values())):
        raise SourceNotReady("Exposure formula returned invalid scores or weights")
    estimates = {
        "people_in_hazard_index_zone_estimate": float(np.sum(population * areas)),
        "building_count_in_zone": int(sum(counts["buildings"].values())),
        "residential_building_count_in_zone": int(counts["buildings"].get("residential", 0)),
        "road_length_m_in_zone": float(road_lengths["roads"]),
        "critical_asset_count_in_zone": int(sum(counts["critical_infrastructure"].values())),
        "critical_assets_by_type": counts["critical_infrastructure"],
        "cropland_area_km2_in_zone_estimate": float(np.sum(cropland * areas)),
        "livestock_in_zone_estimate": float(np.sum(livestock * areas)),
        "industrial_commercial_count_in_zone": (int(sum(counts["economic_assets"].values()))
                                                 if "economic_assets" in counts else None),
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    spec = RasterSpec.from_bbox(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height,
                                crs_epsg=int(grid.crs.split(":", 1)[1]))
    def layer(values):
        raster = np.full(zone_mask.shape, _NODATA, dtype="float32")
        raster[zone_mask] = np.asarray(values, dtype="float32")
        return raster
    raster = layer(computed.scores.to_numpy())
    period = request.period.model_dump(mode="json")
    aoi_west, aoi_south, aoi_east, aoi_north = shape(aoi_geometry).bounds
    metadata = {"crs": grid.crs, "datum": CRS.from_user_input(grid.crs).datum.name,
                "vertical_datum": bindings.upstream["hazard"].result.output_files["flood_hazard"]["gis_metadata"]["datum"],
                "bounds": [grid.west, grid.south, grid.east, grid.north],
                "aoi_bounds_wgs84": {"west": aoi_west, "south": aoi_south,
                                      "east": aoi_east, "north": aoi_north},
                "spatial_resolution": {"x": abs(transform.a), "y": abs(transform.e), "unit": "m"},
                "nodata": _NODATA, "units": "index_0_1", "target_period": period,
                "producer": "NOVA GeoRisk", "product_key": "flood_exposure",
                "result_version": result_version, "legend": _LEGEND,
                "hazard_min_level": request.exposure_options.hazard_min_level,
                "hazard_result_id": str(bindings.upstream["hazard"].result.id),
                "hazard_result_lineage": bindings.upstream["hazard"].lineage(),
                "scientific_basis": "estimated assets inside a Hazard-index class, not observed inundation"}
    entries = {}
    path = output_directory / "flood-exposure-index.cog.tif"
    write_cog(str(path), raster, spec, nodata=_NODATA)
    def raster_entry(path: Path, key: str):
        gis = {**metadata, "product_key": key, "legend": _LEGEND if key == "flood_exposure" else None}
        return artifact_entry(path, label=key.replace("_", " ").title(), media_type="image/tiff",
            artifact_type="raster", result_version=result_version, role="product", product_key=key,
            delivery_type="raster", format_name="cog", gis_metadata=gis,
            layer={"layer_type": "raster", "crs": grid.crs, "units": "index_0_1", "nodata": _NODATA,
                   "bounding_box": {"west": grid.west, "south": grid.south, "east": grid.east, "north": grid.north},
                   "spatial_resolution": metadata["spatial_resolution"],
                   "legend": gis["legend"],
                   "renderable": True, "available_delivery_types": ["raster"], "planned_delivery_types": []})
    entries["flood_exposure"] = raster_entry(path, "flood_exposure")
    for key in frame:
        indicator_path = output_directory / f"exposure-indicator-{key}.cog.tif"
        write_cog(str(indicator_path), layer(computed.normalized_data[key].to_numpy()), spec, nodata=_NODATA)
        entries[f"indicator_{key}"] = raster_entry(indicator_path, f"indicator_{key}")
    preview = output_directory / "flood-exposure-preview.png"
    _write_preview(preview, raster, zone_mask)
    entries["flood_exposure_preview"] = artifact_entry(preview, label="Flood Exposure preview",
        media_type="image/png", artifact_type="preview", result_version=result_version, role="product",
        product_key="flood_exposure", delivery_type="preview", format_name="png", gis_metadata=metadata,
        layer={"layer_type": "raster", "crs": grid.crs, "units": "index_0_1", "nodata": _NODATA,
               "renderable": True, "available_delivery_types": ["preview"], "planned_delivery_types": []})
    vector_path = output_directory / "exposed-assets.geojson"
    vector_path.write_text(json.dumps({"type": "FeatureCollection", "features": vectors}, allow_nan=False), encoding="utf-8")
    entries["exposed_assets"] = artifact_entry(vector_path, label="Assets intersecting Hazard index zone",
        media_type="application/geo+json", artifact_type="vector", result_version=result_version,
        role="product", product_key="flood_exposure", delivery_type="vector", format_name="geojson",
        gis_metadata={"crs": "EPSG:4326", "units": "asset_or_road_geometry", "target_period": period},
        layer={"layer_type": "vector", "crs": "EPSG:4326", "units": "asset_or_road_geometry",
               "nodata": None, "renderable": True, "available_delivery_types": ["vector"],
               "planned_delivery_types": []})
    summary = {"status": "completed", "module": "exposure", "product": "Flood Exposure Index",
               "units": "index_0_1", "hazard_zone_basis": "source-bound Hazard index classification, not observed inundation",
               "hazard_min_level": request.exposure_options.hazard_min_level,
               "hazard_zone_cell_count": int(zone_mask.sum()), "hazard_zone_area_km2": float(areas.sum()),
               "minimum": float(computed.scores.min()), "maximum": float(computed.scores.max()),
               "mean": float(computed.scores.mean()), "weights": computed.weights, **estimates}
    provenance = {"engine_key": "firris", "module": "exposure",
                  "formula_implementation": "app.services.firas.exposure.compute_exposure_index",
                  "source_bindings": bindings.lineage(), "upstream_results": {"hazard": bindings.upstream["hazard"].lineage()},
                  "source_quality_assessment": {role: source.manifest.quality_assessment.model_dump(mode="json")
                                                for role, source in bindings.sources.items()},
                  "weights": computed.weights, "entropy": computed.entropy,
                  "indicator_units": {key: _RAW_UNITS[key] for key in frame},
                  "normalization_ranges": {key: {"raw_min": float(frame[key].min()), "raw_max": float(frame[key].max()),
                                                  "raw_unit": _RAW_UNITS[key]} for key in frame},
                  "indicator_directions": {key: DEFAULT_EXPOSURE_DIRECTIONS[key].value for key in frame},
                  "processing": {"hazard_threshold": threshold, "hazard_level": request.exposure_options.hazard_min_level,
                                 "raster_resampling": "area-average for density/fraction; no upsampling",
                                 "vector_intersection": "projected geometry clipped to AOI and selected Hazard cells",
                                 "population_count_method": "people/km2 times WGS84 geodesic clipped zone-cell km2; uniform-within-cell estimate",
                                 "asset_count_method": "one unique ID per intersecting building/asset",
                                 "road_length_method": "WGS84 geodesic length of projected-clipped line segments, metres",
                                 "spatial_alignment": bindings.alignment, "temporal_period": period},
                  "uncertainty": {role: source.manifest.uncertainty.model_dump() for role, source in bindings.sources.items()},
                  "analysis_readiness_rechecked_at_execution": True,
                  "validation_limitations": ["Hazard class is not observed flood extent",
                    "Population/cropland/livestock counts assume uniform density within source cells",
                    "No independent authoritative exposure inventory accuracy was assessed"]}
    cell_table = pd.DataFrame({"row": rows, "col": cols, "zone_area_km2": areas,
                               "hazard_index": hazard_values[zone_mask],
                               "exposure_index": computed.scores.to_numpy(),
                               "population_estimate": population * areas,
                               "building_count": allocations["buildings"],
                               "road_length_m": allocations["roads"],
                               "critical_asset_count": allocations["critical_infrastructure"],
                               "cropland_area_km2_estimate": cropland * areas,
                               "livestock_estimate": livestock * areas})
    for key in frame:
        cell_table[key] = frame[key].to_numpy()
    csv_path = output_directory / "exposure-zone-statistics.csv"
    xlsx_path = output_directory / "exposure-zone-statistics.xlsx"
    pdf_path = output_directory / "flood-exposure-report.pdf"
    export_csv(cell_table, str(csv_path))
    generate_excel_report({"Zone Cells": cell_table,
                           "Summary": pd.DataFrame([{key: json.dumps(value) if isinstance(value, dict) else value
                                                      for key, value in summary.items()}]),
                           "Weights": pd.DataFrame([{"indicator": key, "weight": value}
                                                    for key, value in computed.weights.items()])}, str(xlsx_path))
    generate_pdf_report(ReportContext(project_name=str(request.project_id), aoi_name=str(request.aoi_id),
        index_summaries=[IndexSummary(name="Flood Exposure Index (E)", mean=summary["mean"],
                                      min=summary["minimum"], max=summary["maximum"],
                                      classification="Hazard-index zone")],
        notes=(f"Hazard class: {request.exposure_options.hazard_min_level} or higher. "
               f"Estimated people in zone: {estimates['people_in_hazard_index_zone_estimate']:.1f}; "
               f"buildings: {estimates['building_count_in_zone']}; "
               f"roads: {estimates['road_length_m_in_zone']:.1f} m; "
               f"critical assets: {estimates['critical_asset_count_in_zone']}. "
               "These are index-zone intersections, not observed flood impacts. "
               "See packaged provenance and uncertainty metadata.")), str(pdf_path))
    reports = {
        "exposure_csv": artifact_entry(csv_path, label="Exposure zone statistics CSV", media_type="text/csv",
            artifact_type="report", result_version=result_version, role="export", delivery_type="csv", format_name="csv"),
        "exposure_excel": artifact_entry(xlsx_path, label="Exposure zone statistics Excel",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", artifact_type="report",
            result_version=result_version, role="export", delivery_type="excel", format_name="xlsx"),
        "exposure_pdf": artifact_entry(pdf_path, label="Flood Exposure report", media_type="application/pdf",
            artifact_type="report", result_version=result_version, role="export", delivery_type="pdf", format_name="pdf"),
    }
    exports = build_result_exports(output_directory, task_id=task_id,
        project_id=str(request.project_id), aoi_id=str(request.aoi_id), engine_key="firris",
        engine_version="source-bound-exposure-v1", result_type="source_bound_exposure",
        result_version=result_version, summary=summary, provenance=provenance,
        gis_metadata=metadata, product_entries=entries, supplemental_entries=reports)
    return EngineExecutionOutput(result_type="source_bound_exposure", summary=summary,
                                 provenance=provenance, output_files={**entries, **reports, **exports})
