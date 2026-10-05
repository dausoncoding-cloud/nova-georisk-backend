"""Reviewed ancillary inputs and DEM derivatives, separate from flood inference."""
import json
from types import SimpleNamespace

import numpy as np
from pyproj import CRS
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds, xy
from rasterio.warp import reproject, Resampling, transform_geom
from shapely.geometry import shape, mapping

from app.platform.engines.base import EngineExecutionOutput
from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.gee.firris_contracts import validate_grid
from app.services.hydrology.watershed import compute_slope, compute_flow_direction, compute_flow_accumulation, compute_twi
from app.services.maps.export import RasterSpec, write_cog
from app.services.source_data.alignment import align_raster_source
from app.services.source_data.hazard import _rainfall
from app.services.source_data.readiness import SourceNotReady

UNITS = {"slope": "degree", "aspect": "degree clockwise from north; flat cells nodata",
         "curvature": "1/m (elevation Laplacian)", "flow_direction": "ESRI D8 code; 0 sink/no outflow",
         "flow_accumulation": "m2 (includes own cell)", "twi": "dimensionless"}


def terrain_metrics(source, grid, aoi_geometry, requested):
    """Derive on full reviewed DEM, then explicitly align; never route on clipped AOI."""
    crs = CRS.from_user_input(grid.crs)
    if not crs.is_projected or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in crs.axis_info[:2]):
        raise SourceNotReady("Terrain requires projected metre coordinates")
    if source.manifest.units != "m" or source.manifest.crs != grid.crs or not source.manifest.vertical_datum:
        raise SourceNotReady("DEM CRS/vertical units/datum are incompatible")
    checks = source.evidence.get("checks", {})
    if not checks.get("hydrologic_coverage_verified") or not checks.get("dem_conditioning_verified"):
        raise SourceNotReady("DEM requires reviewed conditioning and upstream coverage")
    target = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    with MemoryFile(source.data) as memory, memory.open() as raster:
        validate_grid(raster.crs, raster.transform)
        if raster.crs.to_string() != source.manifest.crs or raster.count != 1 or raster.nodata != source.manifest.nodata:
            raise SourceNotReady("DEM bytes differ from approved metadata")
        if raster.width * raster.height > 250_000 or min(raster.shape) < 5:
            raise SourceNotReady("DEM dimensions exceed bounded terrain policy or lack derivative support")
        cell = raster.transform.a
        if not np.isclose(cell, -raster.transform.e) or target.a < cell * .999999 or -target.e < cell * .999999:
            raise SourceNotReady("Terrain requires square native metric cells and prohibits upsampling")
        if not (grid.west > raster.bounds.left + 2 * cell and grid.east < raster.bounds.right - 2 * cell
                and grid.south > raster.bounds.bottom + 2 * cell and grid.north < raster.bounds.top - 2 * cell):
            raise SourceNotReady("DEM requires a two-cell derivative border around target grid")
        dem = raster.read(1, masked=True)
        if np.ma.getmaskarray(dem).any() or not np.isfinite(dem.data).all():
            raise SourceNotReady("DEM gaps cannot be filled for terrain routing")
        raw = dem.data.astype(float)
        dy, dx = np.gradient(raw, cell)
        aspect = np.mod(np.degrees(np.arctan2(-dx, dy)), 360)
        aspect[np.hypot(dx, dy) == 0] = np.nan
        curvature = np.gradient(dx, cell, axis=1) + np.gradient(dy, cell, axis=0)
        flow = compute_flow_direction(raw)
        accumulation = compute_flow_accumulation(raw, flow)
        available = {"slope": compute_slope(raw, cell), "aspect": aspect, "curvature": curvature,
                     "flow_direction": flow.astype(float), "flow_accumulation": accumulation * cell**2}
        if "twi" in requested:
            available["twi"] = compute_twi(raw, accumulation, cell)
        result = {}
        mask = geometry_mask([transform_geom("EPSG:4326", grid.crs, aoi_geometry)],
            out_shape=(grid.height, grid.width), transform=target, invert=True)
        if not mask.any():
            raise SourceNotReady("Terrain output grid does not intersect AOI")
        for name in requested:
            if name not in UNITS:
                raise SourceNotReady("Unsupported terrain product")
            destination = np.full(mask.shape, np.nan)
            reproject(available[name], destination, src_transform=raster.transform, src_crs=raster.crs,
                      src_nodata=np.nan, dst_transform=target, dst_crs=grid.crs, dst_nodata=np.nan,
                      resampling=Resampling.nearest)
            destination[~mask] = np.nan
            result[name] = destination
    return result, {"source": source.lineage(), "native_cell_m": cell,
        "derivative_support": "full reviewed DEM before AOI masking; two-cell output border",
        "alignment": "explicit nearest neighbour; no upsampling; nodata preserved",
        "curvature_definition": "d2z/dx2 + d2z/dy2, not profile/plan curvature",
        "aspect_definition": "downslope clockwise from north; flat cells undefined",
        "flow_method": "existing D8 steepest descent; sinks retain code 0; no new conditioning",
        "twi_policy": "existing reviewed formula with 0.1 degree slope floor; explicit request only",
        "excluded_products": ["SPI: no existing reviewed FIRRIS implementation"], "units": UNITS}


def execute_satellite_preprocessing(bindings, aoi_geometry, output_directory, result_version, *, task_id):
    grid = bindings.request.target_grid
    crs = CRS.from_user_input(grid.crs)
    if not crs.is_projected or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in crs.axis_info[:2]):
        raise SourceNotReady("Climate interpolation requires a projected metre target grid")
    if grid.width * grid.height > 25_000:
        raise SourceNotReady("Preprocessing grid exceeds bounded 25,000-cell policy")
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    mask = geometry_mask([transform_geom("EPSG:4326", grid.crs, aoi_geometry)],
        out_shape=(grid.height, grid.width), transform=transform, invert=True)
    if not mask.any():
        raise SourceNotReady("Preprocessing grid does not intersect AOI")
    arrays, provenance, entries = {}, {}, {}
    for role in ("soil", "population", "land_cover"):
        if role not in bindings.sources:
            continue
        arrays[role], source_mask, provenance[role] = align_raster_source(bindings.sources[role], grid, aoi_geometry)
        if not np.array_equal(source_mask, mask):
            raise SourceNotReady("Covariate AOI grid is inconsistent")
    if "climate" in bindings.sources:
        rows, cols = np.where(mask)
        xs, ys = xy(transform, rows, cols)
        climate, climate_qa = _rainfall(SimpleNamespace(sources={"rainfall": bindings.sources["climate"]},
                                                      request=bindings.request), np.asarray(xs), np.asarray(ys))
        arrays["climate"] = np.full(mask.shape, np.nan)
        arrays["climate"][mask] = climate
        provenance["climate"] = {**climate_qa, "units": "mm/h", "source_variable": "observed rainfall intensity; not general climate prediction"}
    units = {role: bindings.sources[role].manifest.units for role in arrays}
    if "climate" in arrays:
        units["climate"] = "mm/h"
    if bindings.request.satellite_options.terrain_products:
        terrain, record = terrain_metrics(bindings.sources["terrain"], grid, aoi_geometry,
                                           bindings.request.satellite_options.terrain_products)
        arrays.update({"terrain_" + key: value for key, value in terrain.items()})
        units.update({"terrain_" + key: UNITS[key] for key in terrain})
        provenance["terrain"] = record
    output_directory.mkdir(parents=True, exist_ok=True)
    spec = RasterSpec(transform, crs.to_epsg())
    if spec.crs_epsg is None:
        raise SourceNotReady("Preprocessing exports require an EPSG CRS")
    for role, array in arrays.items():
        path = output_directory / (role + ".tif")
        write_cog(str(path), np.where(np.isfinite(array), array, -9999).astype("float32"), spec, nodata=-9999)
        entries[role] = artifact_entry(path, label=role, media_type="image/tiff", artifact_type="raster",
            result_version=result_version, role="product", product_key=role, delivery_type="cog", format_name="cog",
            gis_metadata={"crs": grid.crs, "units": units[role], "nodata": -9999,
                          "width": grid.width, "height": grid.height, "transform": list(transform)[:6],
                          "spatial_resolution": {"x": transform.a, "y": -transform.e, "unit": "m"},
                          "bounding_box": {"west": grid.west, "south": grid.south, "east": grid.east, "north": grid.north}})
    for role in ("roads", "rivers"):
        if role not in bindings.sources:
            continue
        collection = json.loads(bindings.sources[role].data)
        features = []
        for feature in collection["features"]:
            intersection = shape(feature["geometry"]).intersection(shape(aoi_geometry))
            if not intersection.is_empty:
                features.append({**feature, "geometry": mapping(intersection)})
        path = output_directory / (role + ".geojson")
        path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
        entries[role] = artifact_entry(path, label=role, media_type="application/geo+json", artifact_type="vector",
            result_version=result_version, role="product", product_key=role, delivery_type="geojson", format_name="geojson",
            gis_metadata={"crs": "EPSG:4326", "units": "source network geometry"})
        provenance[role] = {"method": "geometric AOI intersection; vector geometry retained in WGS84",
                            "grid_policy": "vector support; no implicit rasterization", "feature_count": len(features)}
    provenance = {"sources": bindings.lineage(), "processing": provenance, "target_grid": grid.model_dump(),
                  "period": bindings.request.period.model_dump(mode="json"),
                  "purpose": "sourced ancillary ingestion; no implicit modification of satellite model features",
                  "scientific_validation": "not asserted; source review remains required"}
    summary = {"status": "completed", "covariates": list(bindings.sources), "products": list(entries)}
    exports = build_result_exports(output_directory, task_id=task_id, project_id=str(bindings.request.project_id),
        aoi_id=str(bindings.request.aoi_id), engine_key="firris", engine_version="1.0",
        result_type="source_bound_satellite_preprocessing", result_version=result_version,
        summary=summary, provenance=provenance, gis_metadata={"crs": grid.crs}, product_entries=entries)
    return EngineExecutionOutput("source_bound_satellite_preprocessing", summary, provenance, {**entries, **exports})
