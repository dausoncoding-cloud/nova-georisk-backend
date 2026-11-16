"""Read-only acquisition of the GloFAS v2.1 flood hazard maps over an AOI (Depth & Exposure module, plan item 1.1).

The seven depth bands and the two flag bands are read on the dataset's own 3-arc-second grid (no resampling for the
statistics) with Earth Engine ``computePixels``, in row blocks that stay under the request limit. Nothing is
exported. Cells outside every GloFAS tile footprint are no-data; inside the footprint a masked depth means dry.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
from rasterio.transform import Affine
from shapely.geometry import shape

from app.services.firris.hazard_sources import GLOFAS_ASSET, GLOFAS_VERSION, RETURN_PERIODS

DEPTH_BANDS = tuple(f"RP{period}_depth" for period in RETURN_PERIODS)
FLAG_BANDS = ("permanent_water_class", "spurious_depth_category")
BANDS = DEPTH_BANDS + FLAG_BANDS
NODATA = -9999.0
REQUEST_LIMIT_BYTES = 40 * 1024 * 1024  # below the ~48 MiB computePixels limit
MAX_CELLS = 6_000_000  # about 50,000 km² at 3″; larger AOIs are refused with a reason


class HazardUnavailable(Exception):
    """The modelled hazard cannot be provided for this AOI (the reason is shown to the user)."""


@dataclass
class GlofasStack:
    depth: dict[int, np.ndarray]          # return period -> depth (m); NaN = dry or no data
    permanent_water: np.ndarray           # bool
    spurious: np.ndarray                  # bool
    covered: np.ndarray                   # bool: inside a GloFAS tile footprint
    transform: Affine
    crs: str
    tiles: list[dict[str, Any]] = field(default_factory=list)
    footprint: dict | None = None         # GeoJSON union of the tile footprints

    def provenance(self) -> dict[str, Any]:
        return {"asset": GLOFAS_ASSET, "version": GLOFAS_VERSION, "tiles": self.tiles, "crs": self.crs,
                "grid_transform": list(self.transform)[:6], "shape": list(self.covered.shape),
                "resolution_deg": abs(self.transform.a), "bands": list(BANDS), "resampling": "none (native grid)",
                "acquired_at": datetime.now(timezone.utc).isoformat()}


def native_grid(origin_x: float, origin_y: float, scale_x: float, scale_y: float, bounds) -> tuple[Affine, int, int]:
    """The dataset grid snapped outward around ``bounds`` (west, south, east, north): transform, width, height."""
    west, south, east, north = bounds
    sy = abs(scale_y)
    eps = 1e-6  # a bound that sits on a grid line (to float precision) does not add a cell
    col0 = math.floor((west - origin_x) / scale_x + eps)
    col1 = math.ceil((east - origin_x) / scale_x - eps)
    row0 = math.floor((origin_y - north) / sy + eps)
    row1 = math.ceil((origin_y - south) / sy - eps)
    transform = Affine(scale_x, 0.0, origin_x + col0 * scale_x, 0.0, -sy, origin_y - row0 * sy)
    return transform, max(col1 - col0, 1), max(row1 - row0, 1)


def row_blocks(height: int, width: int, bands: int, *, limit: int = REQUEST_LIMIT_BYTES) -> list[tuple[int, int]]:
    """Row ranges whose float32 request size stays under ``limit``."""
    rows = max(1, limit // max(1, width * bands * 4))
    return [(start, min(height, start + rows)) for start in range(0, height, rows)]


def coverage_mask(footprint_geojson: dict | None, transform: Affine, width: int, height: int) -> np.ndarray:
    from rasterio.features import rasterize
    if not footprint_geojson:
        return np.zeros((height, width), dtype=bool)
    return rasterize([(footprint_geojson, 1)], out_shape=(height, width), transform=transform, fill=0,
                     all_touched=False, dtype="uint8").astype(bool)


def acquire_glofas(aoi_geometry: dict) -> GlofasStack:
    """Read the GloFAS v2.1 hazard bands over the AOI (Earth Engine, read-only)."""
    import ee

    from app.services.gee import auth

    auth.initialize_gee()
    aoi = ee.Geometry(aoi_geometry)
    collection = ee.ImageCollection(GLOFAS_ASSET).filterBounds(aoi)
    info = collection.map(lambda image: ee.Feature(image.geometry(), {
        "index": image.get("system:index"), "id": image.get("id"), "time_start": image.get("system:time_start")})).getInfo()
    tiles = [{"index": f["properties"]["index"], "id": f["properties"]["id"],
              "production_date": datetime.fromtimestamp(f["properties"]["time_start"] / 1000, timezone.utc).date().isoformat()}
             for f in info.get("features", [])]
    if not tiles:
        raise HazardUnavailable("The area lies outside the GloFAS flood hazard maps (no tile covers it; the maps exclude "
                                "small islands and river basins under 500 km²).")
    footprint = shape(info["features"][0]["geometry"])
    for feature in info["features"][1:]:
        footprint = footprint.union(shape(feature["geometry"]))
    projection = collection.first().select(DEPTH_BANDS[0]).projection().getInfo()
    sx, _, ox, _, sy, oy = projection["transform"]
    transform, width, height = native_grid(ox, oy, sx, sy, shape(aoi_geometry).bounds)
    if width * height > MAX_CELLS:
        raise HazardUnavailable(f"The area is too large for the modelled hazard ({width * height:,} GloFAS cells; "
                                f"limit {MAX_CELLS:,}). Split the area.")
    image = collection.mosaic().select(list(BANDS)).toFloat().unmask(NODATA)
    out = np.full((len(BANDS), height, width), NODATA, dtype=np.float32)
    for start, stop in row_blocks(height, width, len(BANDS)):
        block = transform * Affine.translation(0, start)
        data = ee.data.computePixels({
            "expression": image, "fileFormat": "NUMPY_NDARRAY",
            "grid": {"dimensions": {"width": width, "height": stop - start},
                     "affineTransform": {"scaleX": block.a, "shearX": 0, "translateX": block.c,
                                         "shearY": 0, "scaleY": block.e, "translateY": block.f},
                     "crsCode": "EPSG:4326"}})
        for index, band in enumerate(BANDS):
            out[index, start:stop] = data[band]
    from shapely.geometry import mapping
    covered = coverage_mask(mapping(footprint), transform, width, height)
    depth = {}
    for index, period in enumerate(RETURN_PERIODS):
        values = out[index]
        depth[period] = np.where(covered & (values != NODATA), values, np.nan).astype(np.float32)
    flags = {band: out[len(DEPTH_BANDS) + i] for i, band in enumerate(FLAG_BANDS)}
    return GlofasStack(depth=depth, permanent_water=covered & (flags["permanent_water_class"] == 1),
                       spurious=covered & (flags["spurious_depth_category"] == 1), covered=covered, transform=transform,
                       crs="EPSG:4326", tiles=tiles, footprint=mapping(footprint))
