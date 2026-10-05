"""Exact-grid annual and timestamped-inundation source co-registration."""
from __future__ import annotations

from datetime import timedelta, timezone

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import transform_geom

from app.services.source_data.readiness import SourceNotReady


def aoi_mask(grid, aoi_geometry: dict) -> np.ndarray:
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    geometry = transform_geom("EPSG:4326", grid.crs, aoi_geometry)
    mask = geometry_mask([geometry], out_shape=(grid.height, grid.width), transform=transform, invert=True)
    if not mask.any():
        raise SourceNotReady("Temporal product grid has no AOI cells")
    return mask


def exact_binary_raster(source, grid, mask: np.ndarray) -> np.ndarray:
    """No interpolation or resampling of observed annual/time-slice classes."""
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    try:
        with MemoryFile(source.data) as memory, memory.open() as raster:
            if (raster.driver != "GTiff" or raster.count != 1 or raster.crs is None
                    or raster.crs.to_string() != grid.crs or raster.width != grid.width
                    or raster.height != grid.height or not raster.transform.almost_equals(transform)
                    or raster.nodata != source.manifest.nodata):
                raise SourceNotReady("Temporal source CRS, grid or nodata differs")
            values = raster.read(1, masked=True)
            if not (~np.ma.getmaskarray(values))[mask].all():
                raise SourceNotReady("Temporal source does not cover every AOI cell")
            observed = np.asarray(values.data)[mask]
            if not np.isfinite(observed).all() or not np.isin(observed, [0, 1]).all():
                raise SourceNotReady("Temporal source must contain valid binary AOI observations")
            return np.asarray(values.data, dtype="uint8")
    except (rasterio.errors.RasterioError, OSError, ValueError) as exc:
        raise SourceNotReady("Temporal source GeoTIFF is unreadable") from exc


def validate_annual_sources(request, sources: dict, aoi_geometry: dict):
    grid = request.target_grid
    start, end = request.period.start.astimezone(timezone.utc), request.period.end.astimezone(timezone.utc)
    years = list(range(start.year, end.year + 1))
    if (len(years) < 10 or (start.month, start.day, start.hour, start.minute, start.second) != (1, 1, 0, 0, 0)
            or (end.month, end.day, end.hour, end.minute, end.second) != (12, 31, 23, 59, 59)
            or set(sources) != {f"year_{year}" for year in years}):
        raise SourceNotReady("AEP requires at least ten complete, consecutive annual observations")
    mask = aoi_mask(grid, aoi_geometry)
    definitions = set()
    arrays = []
    for year in years:
        source = sources[f"year_{year}"]
        manifest = source.manifest
        if (manifest.category != "annual_inundation_observation" or manifest.observation_year != year
                or not source.evidence.get("checks", {}).get("annual_record_complete_verified")):
            raise SourceNotReady("Annual observation year or completeness review is invalid")
        definitions.add(manifest.event_definition)
        arrays.append(exact_binary_raster(source, grid, mask))
    if len(definitions) != 1:
        raise SourceNotReady("Annual observations do not share one fixed exceedance event definition")
    return arrays, mask, {"record_length_years": len(years), "observation_years": years,
                          "event_definition": next(iter(definitions)),
                          "method": "empirical annual event exceedance count / complete observation years",
                          "minimum_record_rule": "at least ten consecutive complete years; not a guarantee of precision"}


def validate_duration_sources(request, sources: dict, aoi_geometry: dict):
    if request.duration_options is None or request.duration_options.gap_policy != "reject":
        raise SourceNotReady("Duration requires explicit reject-on-gap temporal resolution")
    roles = [f"slice_{index}" for index in range(len(sources))]
    if len(roles) < 3 or set(sources) != set(roles):
        raise SourceNotReady("Duration requires at least three ordered time slices")
    cadence = timedelta(hours=request.duration_options.temporal_resolution_hours)
    mask = aoi_mask(request.target_grid, aoi_geometry)
    arrays, timestamps = [], []
    for role in roles:
        source = sources[role]
        manifest = source.manifest
        if manifest.category != "inundation_time_slice" or manifest.temporal_coverage.start != manifest.temporal_coverage.end:
            raise SourceNotReady("Duration source is not a timestamped inundation slice")
        timestamps.append(manifest.temporal_coverage.start)
        arrays.append(exact_binary_raster(source, request.target_grid, mask))
    if (timestamps[0] != request.period.start or timestamps[-1] != request.period.end
            or any(timestamps[index + 1] - timestamps[index] != cadence for index in range(len(timestamps) - 1))):
        raise SourceNotReady("Inundation timestamps have gaps, duplicates or incompatible period endpoints")
    if arrays[0][mask].any() or arrays[-1][mask].any():
        raise SourceNotReady("Duration is left- or right-censored; first and last AOI slices must be dry")
    return arrays, mask, {"timestamps": [value.isoformat() for value in timestamps],
                          "temporal_resolution_hours": request.duration_options.temporal_resolution_hours,
                          "gap_policy": "reject", "endpoint_policy": "first and last AOI slices dry",
                          "method": "sum flooded interval-start states × verified fixed cadence"}
