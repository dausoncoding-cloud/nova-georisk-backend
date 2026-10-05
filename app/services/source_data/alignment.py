"""Explicit, gap-intolerant raster co-registration and AOI clipping."""
from __future__ import annotations

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_geom

from app.schemas.source_bindings import RasterGrid
from app.services.source_data.readiness import ReadySource, SourceNotReady


def align_raster_bundle(sources: dict[str, ReadySource], grid: RasterGrid, aoi_wgs84: dict):
    """Require a common vertical datum and complete co-registered AOI grid."""
    datums = {source.manifest.vertical_datum for source in sources.values() if source.manifest.vertical_datum}
    if len(datums) > 1:
        raise SourceNotReady("Raster vertical datums are incompatible")
    arrays, provenance = {}, {}
    common_mask = None
    for role, source in sources.items():
        array, mask, record = align_raster_source(source, grid, aoi_wgs84)
        if common_mask is not None and not np.array_equal(mask, common_mask):
            raise SourceNotReady("Raster AOI masks are incompatible")
        common_mask = mask
        arrays[role] = array
        provenance[role] = record
    return arrays, common_mask, provenance


def align_raster_source(source: ReadySource, grid: RasterGrid, aoi_wgs84: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    """Nearest-neighbour resampling only; require complete observed AOI coverage."""
    if source.manifest.category not in {
        "water_surface_elevation", "terrain_dem", "soil_permeability", "land_cover",
        "inundation_time_slice", "population_density", "cropland_fraction", "livestock_density",
    }:
        raise SourceNotReady("Only registered raster categories can be grid-aligned")
    transform = from_bounds(grid.west, grid.south, grid.east, grid.north, grid.width, grid.height)
    geometry = transform_geom("EPSG:4326", grid.crs, aoi_wgs84)
    aoi_mask = geometry_mask([geometry], out_shape=(grid.height, grid.width), transform=transform, invert=True)
    if not aoi_mask.any():
        raise SourceNotReady("Target grid does not intersect the AOI")
    with MemoryFile(source.data) as memory, memory.open() as raster:
        if raster.crs is None or raster.crs.to_string() != source.manifest.crs:
            raise SourceNotReady("Raster CRS differs from approved manifest")
        suggested, suggested_width, suggested_height = calculate_default_transform(
            raster.crs, grid.crs, raster.width, raster.height, *raster.bounds,
        )
        native_x, native_y = abs(suggested.a), abs(suggested.e)
        target_x, target_y = abs(transform.a), abs(transform.e)
        if target_x < native_x * 0.95 or target_y < native_y * 0.95:
            raise SourceNotReady("Target grid would upsample beyond approved source resolution")
        destination = np.full((grid.height, grid.width), np.nan, dtype="float64")
        reproject(
            source=rasterio.band(raster, 1), destination=destination,
            src_transform=raster.transform, src_crs=raster.crs, src_nodata=raster.nodata,
            dst_transform=transform, dst_crs=grid.crs, dst_nodata=np.nan,
            resampling=Resampling.nearest,
        )
    if not np.isfinite(destination[aoi_mask]).all():
        raise SourceNotReady("Approved source does not cover every AOI cell in the target grid")
    destination[~aoi_mask] = np.nan
    return destination, aoi_mask, {
        "source_dataset_id": str(source.dataset.id), "source_crs": source.manifest.crs,
        "target_crs": grid.crs, "resampling": "nearest", "aoi_clip": True,
        "target_resolution": {"x": target_x, "y": target_y},
        "source_resolution_in_target_crs": {"x": native_x, "y": native_y},
    }
