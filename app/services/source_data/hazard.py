"""Approved FIRRIS Module 5 Hazard inputs to the unchanged entropy formula.

This adapter derives indicators from reviewed source bytes. It does not use a
Random Forest score, infer absent observations, or calculate return periods.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject
from shapely.geometry import MultiPoint, Point, box, shape
from shapely.ops import transform as transform_shape, unary_union

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.firas.hazard import DEFAULT_HAZARD_DIRECTIONS, compute_hazard_index
from app.services.hydrology.rainfall import interpolate_rainfall_idw
from app.services.hydrology.watershed import compute_flow_accumulation, compute_flow_direction, compute_slope
from app.services.maps.export import RasterSpec, write_cog
from app.services.source_data.alignment import align_raster_source
from app.services.source_data.bindings import ResolvedBindings
from app.services.source_data.readiness import SourceNotReady


# FIRRIS scientific specification, land-cover scoring tables (MODIS and ESA).
# The numerical ranks are fixed by that source, not supplied by a client.
_LAND_COVER = {
    "esa_worldcover": {10: 1, 20: 3, 30: 3, 40: 4, 50: 5, 60: 4, 70: 4, 80: 5, 90: 5, 95: 3, 100: 3},
    "modis_lc_type1": {1: 1, 2: 1, 3: 2, 4: 2, 5: 1, 6: 3, 7: 3, 8: 3, 9: 3, 10: 3, 11: 5, 12: 4, 13: 5, 14: 4, 15: 4, 16: 4, 17: 5},
}
_LAND_COVER_NAMES = {
    "esa_worldcover": {10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland",
        50: "Built-up", 60: "Bare / sparse vegetation", 70: "Snow and ice",
        80: "Permanent water bodies", 90: "Herbaceous wetland", 95: "Mangroves",
        100: "Moss and lichen"},
    "modis_lc_type1": {1: "Evergreen Needleleaf Forests", 2: "Evergreen Broadleaf Forests",
        3: "Deciduous Needleleaf Forests", 4: "Deciduous Broadleaf Forests", 5: "Mixed Forests",
        6: "Closed Shrublands", 7: "Open Shrublands", 8: "Woody Savannas",
        9: "Savannas", 10: "Grasslands", 11: "Permanent Wetlands", 12: "Cropland",
        13: "Urban and Built-up Lands", 14: "Cropland/Natural Vegetation Mosaic",
        15: "Permanent Snow and Ice", 16: "Bare (sand, rock, soil)", 17: "Water Bodies"},
}
_UNITS = {
    "rainfall_intensity": "mm/h", "slope": "degree", "elevation": "m",
    "distance_to_river": "m", "drainage_density": "km/km2",
    "flow_accumulation": "km2", "soil_permeability": "mm/h",
    "land_use_land_cover": "susceptibility_rank_1_5",
}
_LEGEND = [
    {"label": "Very Low", "min": 0.0, "max": 0.2, "color": "#0B3C5D"},
    {"label": "Low", "min": 0.2, "max": 0.4, "color": "#00B4D8"},
    {"label": "Moderate", "min": 0.4, "max": 0.6, "color": "#F9C74F"},
    {"label": "High", "min": 0.6, "max": 0.8, "color": "#F8961E"},
    {"label": "Extreme", "min": 0.8, "max": 1.0, "color": "#D00000"},
]
_NODATA = -9999.0


def _write_hazard_preview(path: Path, raster: np.ndarray, mask: np.ndarray) -> None:
    """Use the exact five specification classes, with transparent non-AOI pixels."""
    colors = np.array([[int(band["color"][offset:offset + 2], 16) for offset in (1, 3, 5)]
                       for band in _LEGEND], dtype=np.uint8)
    classes = np.searchsorted([0.2, 0.4, 0.6, 0.8], raster, side="left")
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[..., :3][mask] = colors[classes[mask]]
    rgba[..., 3][mask] = 255
    Image.fromarray(rgba, mode="RGBA").save(path)


def _rainfall(bindings: ResolvedBindings, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, dict]:
    from app.services.source_data.stations import rainfall_samples
    coordinates, intensities, record = rainfall_samples(bindings.sources["rainfall"], bindings.request, x, y)
    result = interpolate_rainfall_idw(coordinates, intensities, np.column_stack((x, y)), power=2.0)
    cv = {key: (value if np.isfinite(value) else None) for key, value in (result.cross_validation or {}).items()}
    return result.surface_values, {**record, "method": "IDW", "power": 2.0, "cross_validation": cv}


def _terrain(bindings: ResolvedBindings, transform, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    source = bindings.sources["terrain"]
    grid = bindings.request.target_grid
    with MemoryFile(source.data) as memory, memory.open() as dem:
        if dem.crs.to_string() != grid.crs or dem.nodata != source.manifest.nodata or dem.count != 1:
            raise SourceNotReady("Approved DEM grid metadata changed")
        if dem.width * dem.height > 250_000:
            raise SourceNotReady("DEM exceeds the reviewed D8 execution limit")
        terrain = dem.read(1, masked=True)
        if np.any(np.ma.getmaskarray(terrain)) or not np.isfinite(terrain.data).all():
            raise SourceNotReady("DEM has gaps; hydrologic routing cannot impute elevation")
        cell_x, cell_y = abs(dem.transform.a), abs(dem.transform.e)
        if abs(cell_x - cell_y) > max(cell_x, cell_y) * 1e-6:
            raise SourceNotReady("DEM D8 routing requires square metric cells")
        if (grid.west <= dem.bounds.left + cell_x or grid.east >= dem.bounds.right - cell_x
                or grid.south <= dem.bounds.bottom + cell_y or grid.north >= dem.bounds.top - cell_y):
            raise SourceNotReady("DEM requires a non-AOI border and reviewed upstream coverage")
        raw = np.asarray(terrain.data, dtype=float)
        slope = compute_slope(raw, cell_size=cell_x, unit="degrees")
        accumulation = compute_flow_accumulation(raw, compute_flow_direction(raw)) * cell_x * cell_y / 1_000_000
        derived = {}
        for name, layer in (("slope", slope), ("flow_accumulation", accumulation)):
            destination = np.full(mask.shape, np.nan, dtype="float64")
            reproject(layer, destination, src_transform=dem.transform, src_crs=dem.crs,
                      dst_transform=transform, dst_crs=grid.crs, dst_nodata=np.nan,
                      resampling=Resampling.nearest)
            if not np.isfinite(destination[mask]).all():
                raise SourceNotReady("Derived terrain layer does not cover the AOI")
            derived[name] = destination[mask]
    return derived["slope"], derived["flow_accumulation"], {
        "method": "finite-difference slope; D8 routing on full reviewed DEM before AOI clip",
        "dem_cell_size_m": cell_x, "flow_accumulation_unit": "km2",
        "upstream_coverage_review": source.evidence.get("evidence_refs"),
    }


def _river(bindings: ResolvedBindings, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    source = bindings.sources["river_network"]
    if source.manifest.units != "network_line":
        raise SourceNotReady("River network unit must be network_line")
    transformer = Transformer.from_crs("EPSG:4326", bindings.request.target_grid.crs, always_xy=True)
    features = json.loads(source.data)["features"]
    lines = [transform_shape(transformer.transform, shape(feature["geometry"])) for feature in features]
    network = unary_union(lines)
    window = bindings.request.hazard_options.drainage_window_m
    distances, densities = np.empty(len(x)), np.empty(len(x))
    for index, (cx, cy) in enumerate(zip(x, y)):
        point = Point(cx, cy)
        distances[index] = point.distance(network)
        sample = box(cx - window / 2, cy - window / 2, cx + window / 2, cy + window / 2)
        densities[index] = network.intersection(sample).length / (window * window) * 1000
    return distances, densities, {"method": "exact projected line distance and local stream length / square-window area", "drainage_window_m": window, "network_feature_count": len(lines)}


def _land_cover(bindings: ResolvedBindings, codes: np.ndarray) -> np.ndarray:
    source = bindings.sources["land_cover"]
    scheme = source.manifest.land_cover_scheme
    scores = _LAND_COVER.get(scheme)
    try:
        declared = {int(code) for code in source.manifest.class_scheme}
    except (TypeError, ValueError) as exc:
        raise SourceNotReady("Land-cover class codes must be integers") from exc
    if scores is None or not declared.issubset(scores):
        raise SourceNotReady("Land-cover classes are not in the approved FIRRIS score table")
    names = _LAND_COVER_NAMES[scheme]
    if any(label.strip().casefold() != names[int(code)].casefold()
           for code, label in source.manifest.class_scheme.items()):
        raise SourceNotReady("Land-cover class labels disagree with the selected ESA/MODIS scheme")
    if not np.equal(codes, np.floor(codes)).all() or not set(codes.astype(int)).issubset(scores):
        raise SourceNotReady("Land-cover raster contains an unscored class")
    return np.array([scores[int(code)] for code in codes], dtype=float)


def execute_hazard_module(bindings: ResolvedBindings, aoi_geometry: dict, output_directory: Path,
                          result_version: int, *, task_id: str = "") -> EngineExecutionOutput:
    """Execute Module 5 only on revalidated approved sources; persist protected products."""
    if bindings.request.module != "hazard" or bindings.request.target_grid is None or bindings.request.hazard_options is None:
        raise SourceNotReady("A validated Hazard source-binding request is required")
    grid = bindings.request.target_grid
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    from rasterio.warp import transform_geom
    geometry = transform_geom("EPSG:4326", grid.crs, aoi_geometry)
    mask = geometry_mask([geometry], out_shape=(grid.height, grid.width), transform=transform, invert=True)
    if mask.sum() < 2:
        raise SourceNotReady("Entropy weighting needs at least two AOI raster cells")
    rows, cols = np.nonzero(mask)
    x, y = rasterio.transform.xy(transform, rows, cols, offset="center")
    x, y = np.asarray(x), np.asarray(y)
    terrain, soil, land = (bindings.sources[name] for name in ("terrain", "soil", "land_cover"))
    elevation, _, _ = align_raster_source(terrain, grid, aoi_geometry)
    permeability, _, _ = align_raster_source(soil, grid, aoi_geometry)
    land_codes, _, _ = align_raster_source(land, grid, aoi_geometry)
    slope, accumulation, terrain_provenance = _terrain(bindings, transform, mask)
    rainfall, rainfall_provenance = _rainfall(bindings, x, y)
    distance, density, river_provenance = _river(bindings, x, y)
    raw = {
        "rainfall_intensity": rainfall, "slope": slope, "elevation": elevation[mask],
        "distance_to_river": distance, "drainage_density": density,
        "flow_accumulation": accumulation, "soil_permeability": permeability[mask],
        "land_use_land_cover": _land_cover(bindings, land_codes[mask]),
    }
    if any(not np.isfinite(values).all() for values in raw.values()):
        raise SourceNotReady("Hazard indicators contain missing or non-finite AOI observations")
    frame = pd.DataFrame(raw)
    if all(frame[column].nunique() == 1 for column in frame):
        raise SourceNotReady("All Hazard indicators are constant; informative entropy weights cannot be derived")
    computed = compute_hazard_index(frame)
    if (not np.isfinite(computed.scores.to_numpy()).all()
            or not np.isclose(sum(computed.weights.values()), 1.0)
            or any(weight < 0 for weight in computed.weights.values())):
        raise SourceNotReady("Hazard formula returned invalid scores or weights")
    output_directory.mkdir(parents=True, exist_ok=True)
    spec = RasterSpec.from_bbox(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height,
                                crs_epsg=int(grid.crs.split(":", 1)[1]))
    period = bindings.request.period.model_dump(mode="json")
    metadata = {"crs": grid.crs, "datum": terrain.manifest.vertical_datum,
                "bounds": [grid.west, grid.south, grid.east, grid.north],
                "spatial_resolution": {"x": abs(transform.a), "y": abs(transform.e), "unit": "m"},
                "nodata": _NODATA, "target_period": period, "producer": "NOVA GeoRisk",
                "product_key": "flood_hazard", "result_version": result_version,
                "legend": _LEGEND, "uncertainty": {role: source.manifest.uncertainty.model_dump() for role, source in bindings.sources.items()}}
    def layer(values):
        raster = np.full(mask.shape, _NODATA, dtype="float32")
        raster[mask] = np.asarray(values, dtype="float32")
        return raster
    raster = layer(computed.scores.to_numpy())
    hazard_path = output_directory / "flood-hazard-index.cog.tif"
    write_cog(str(hazard_path), raster, spec, nodata=_NODATA)
    entries = {}
    def raster_entry(path: Path, key: str, units: str, legend=None):
        gis = {**metadata, "units": units, "product_key": key, "legend": legend}
        return artifact_entry(path, label=key.replace("_", " ").title(), media_type="image/tiff",
                              artifact_type="raster", result_version=result_version, role="product",
                              product_key=key, delivery_type="raster", format_name="cog",
                              gis_metadata=gis, layer={"layer_type": "raster", "crs": grid.crs,
                              "units": units, "nodata": _NODATA, "renderable": True,
                              "available_delivery_types": ["raster"], "planned_delivery_types": []})
    entries["flood_hazard"] = raster_entry(hazard_path, "flood_hazard", "index_0_1", _LEGEND)
    for key in DEFAULT_HAZARD_DIRECTIONS:
        path = output_directory / f"hazard-indicator-{key}.cog.tif"
        write_cog(str(path), layer(computed.normalized_data[key].to_numpy()), spec, nodata=_NODATA)
        entries[f"indicator_{key}"] = raster_entry(path, f"indicator_{key}", "index_0_1")
    preview = output_directory / "flood-hazard-preview.png"
    _write_hazard_preview(preview, raster, mask)
    entries["flood_hazard_preview"] = artifact_entry(preview, label="Flood Hazard preview", media_type="image/png",
        artifact_type="preview", result_version=result_version, role="product", product_key="flood_hazard",
        delivery_type="preview", format_name="png", gis_metadata=metadata,
        layer={"layer_type": "preview", "crs": grid.crs, "units": "index_0_1", "nodata": _NODATA,
               "renderable": True, "available_delivery_types": ["preview"], "planned_delivery_types": []})
    summary = {"status": "completed", "module": "hazard", "product": "Flood Hazard Index",
               "units": "index_0_1", "aoi_cell_count": int(mask.sum()),
               "minimum": float(computed.scores.min()), "maximum": float(computed.scores.max()),
               "mean": float(computed.scores.mean()), "weights": computed.weights,
               "scientific_validation": "not independently validated against observed floods"}
    provenance = {"engine_key": "firris", "module": "hazard",
                  "formula_implementation": "app.services.firas.hazard.compute_hazard_index",
                  "formula_variant": "Module 5 entropy-weighted eight-indicator H",
                  "source_bindings": bindings.lineage(), "weights": computed.weights,
                  "source_quality_assessment": {role: source.manifest.quality_assessment.model_dump(mode="json")
                                                for role, source in bindings.sources.items()},
                  "entropy": computed.entropy,
                  "indicator_units": _UNITS,
                  "normalization_ranges": {key: {"raw_min": float(frame[key].min()),
                                                  "raw_max": float(frame[key].max()),
                                                  "raw_unit": _UNITS[key]}
                                            for key in frame},
                  "indicator_directions": {key: value.value for key, value in DEFAULT_HAZARD_DIRECTIONS.items()},
                  "processing": {"rainfall": rainfall_provenance, "terrain": terrain_provenance,
                                 "river_network": river_provenance, "land_cover_scheme": land.manifest.land_cover_scheme,
                                 "spatial_alignment": bindings.alignment, "aoi_clip": True,
                                 "temporal_period": period},
                  "analysis_readiness_rechecked_at_execution": True,
                  "uncertainty": metadata["uncertainty"],
                  "validation_limitations": ["No independent authoritative flood observations were bound or validated",
                                             "D8 upstream coverage relies on administrator-reviewed DEM evidence"]}
    exports = build_result_exports(output_directory, task_id=task_id,
        project_id=str(bindings.request.project_id), aoi_id=str(bindings.request.aoi_id),
        engine_key="firris", engine_version="source-bound-hazard-v1", result_type="source_bound_hazard",
        result_version=result_version, summary=summary, provenance=provenance,
        gis_metadata=metadata, product_entries=entries)
    return EngineExecutionOutput(result_type="source_bound_hazard", summary=summary,
                                 provenance=provenance, output_files={**entries, **exports})
