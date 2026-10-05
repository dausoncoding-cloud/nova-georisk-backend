"""
Map export — Doc 0 / SYSTEM SPEC's "Spatial Outputs (GeoTIFF/GeoJSON)"
requirement, extended with a colourized PNG renderer for quick preview
(using the Doc 2 legends) and a GeoJSON polygon export for vector
products (e.g. flood extent).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.features import shapes as raster_shapes
from rasterio.transform import Affine
from rasterio.warp import transform_geom
from PIL import Image


@dataclass
class RasterSpec:
    """Georeferencing for a raster export: an affine transform + CRS (EPSG code)."""

    transform: Affine
    crs_epsg: int = 4326

    @staticmethod
    def from_bounds(west: float, north: float, pixel_size: float, crs_epsg: int = 4326) -> "RasterSpec":
        """Build a north-up transform from the top-left corner and a uniform pixel size (degrees or metres)."""
        transform = Affine.translation(west, north) @ Affine.scale(pixel_size, -pixel_size)
        return RasterSpec(transform=transform, crs_epsg=crs_epsg)

    @staticmethod
    def from_bbox(
        west: float,
        south: float,
        east: float,
        north: float,
        width: int,
        height: int,
        crs_epsg: int = 4326,
    ) -> "RasterSpec":
        """Build a north-up transform whose outer edges match a bounding box."""
        if width <= 0 or height <= 0 or west >= east or south >= north:
            raise ValueError("A valid bounding box and positive raster dimensions are required.")
        return RasterSpec(
            transform=Affine.translation(west, north)
            @ Affine.scale((east - west) / width, -(north - south) / height),
            crs_epsg=crs_epsg,
        )


def write_geotiff(path: str, array: np.ndarray, spec: RasterSpec, nodata: float | None = None) -> str:
    """
    Write a single-band raster (float or int dtype) to a GeoTIFF.
    Returns the path written, for convenient chaining.
    """
    array = np.asarray(array)
    if array.ndim != 2:
        raise ValueError(f"Expected a 2D array, got shape {array.shape}.")

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=array.dtype,
        crs=f"EPSG:{spec.crs_epsg}",
        transform=spec.transform,
        nodata=nodata,
    ) as dst:
        dst.write(array, 1)

    return path


def write_cog(path: str, array: np.ndarray, spec: RasterSpec, nodata: float | None = None) -> str:
    """Write a single-band Cloud Optimized GeoTIFF and validate its layout.

    Rasterio's COG driver builds internal tiling and overviews.  A hard error is
    preferable to silently labelling an ordinary GeoTIFF as a COG.
    """
    array = np.asarray(array)
    if array.ndim != 2:
        raise ValueError(f"Expected a 2D array, got shape {array.shape}.")
    with rasterio.open(
        path,
        "w",
        driver="COG",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=array.dtype,
        crs=f"EPSG:{spec.crs_epsg}",
        transform=spec.transform,
        nodata=nodata,
        compress="DEFLATE",
        blocksize=512,
        overview_resampling="nearest" if np.issubdtype(array.dtype, np.integer) else "average",
    ) as dst:
        dst.write(array, 1)
    with rasterio.open(path) as src:
        if not src.is_tiled:
            raise RuntimeError("The raster driver did not produce a tiled COG.")
    return path


def read_geotiff(path: str) -> tuple[np.ndarray, RasterSpec]:
    """Read back a single-band GeoTIFF — mainly for round-trip verification."""
    with rasterio.open(path) as src:
        array = src.read(1)
        spec = RasterSpec(transform=src.transform, crs_epsg=src.crs.to_epsg() if src.crs else 4326)
    return array, spec


def colorize_classified_raster(class_labels: np.ndarray, color_map: dict[str, str]) -> Image.Image:
    """
    Render a classified raster (array of string class labels) as an
    RGB PNG using the given {label: hex_color} map — Doc 2's legend
    colours applied directly.
    """
    class_labels = np.asarray(class_labels)
    height, width = class_labels.shape
    rgb = np.zeros((height, width, 3), dtype=np.uint8)

    for label, hex_color in color_map.items():
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        mask = class_labels == label
        rgb[mask] = (r, g, b)

    return Image.fromarray(rgb, mode="RGB")


def write_png(path: str, class_labels: np.ndarray, color_map: dict[str, str]) -> str:
    image = colorize_classified_raster(class_labels, color_map)
    image.save(path)
    return path


def write_continuous_png(
    path: str,
    array: np.ndarray,
    palette: list[str] | None = None,
    nodata: float | None = None,
) -> str:
    """Render a numeric 2D raster to an RGBA preview without changing source values."""
    values = np.asarray(array, dtype=float)
    if values.ndim != 2:
        raise ValueError(f"Expected a 2D array, got shape {values.shape}.")
    palette = palette or ["#0B3C5D", "#00B4D8", "#F9C74F", "#D00000"]
    colors = np.asarray(
        [[int(color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)] for color in palette],
        dtype=float,
    )
    valid = np.isfinite(values)
    if nodata is not None:
        valid &= values != nodata
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    if np.any(valid):
        minimum = float(np.nanmin(values[valid]))
        maximum = float(np.nanmax(values[valid]))
        normalized = np.zeros(values.shape, dtype=float)
        if maximum > minimum:
            normalized[valid] = (values[valid] - minimum) / (maximum - minimum)
        positions = normalized * (len(colors) - 1)
        lower = np.floor(positions).astype(int)
        upper = np.minimum(lower + 1, len(colors) - 1)
        fraction = (positions - lower)[..., None]
        rgb = colors[lower] * (1 - fraction) + colors[upper] * fraction
        rgba[..., :3][valid] = rgb.astype(np.uint8)[valid]
        rgba[..., 3][valid] = 255
    Image.fromarray(rgba, mode="RGBA").save(path)
    return path


def export_flood_extent_geojson(mask: np.ndarray, spec: RasterSpec) -> dict:
    """
    Polygonize contiguous flooded cells and emit RFC 7946 WGS84 GeoJSON.
    Invalid/nodata cells must already be excluded from ``mask``.
    """
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 2:
        raise ValueError("Flood extent mask must be two-dimensional.")
    features = []
    source_crs = f"EPSG:{spec.crs_epsg}"
    for geometry, value in raster_shapes(mask.astype(np.uint8), mask=mask, transform=spec.transform, connectivity=4):
        if value != 1:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": transform_geom(source_crs, "EPSG:4326", geometry),
                "properties": {"class": "flooded"},
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }
