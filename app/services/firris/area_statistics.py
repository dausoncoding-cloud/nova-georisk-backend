"""Raster-cell area accounting for FIRRIS outputs.

This reports delivered valid-cell area, not the cadastral area of the AOI.
Geographic cells use the CRS ellipsoid; projected cells use planar map units.
"""
from __future__ import annotations

import numpy as np
from pyproj import CRS

from app.services.maps.export import RasterSpec


def raster_area_statistics(values: np.ndarray, spec: RasterSpec, *, nodata_mask: np.ndarray | None = None) -> dict:
    raster = np.asarray(values)
    if raster.ndim != 2:
        raise ValueError("Area statistics require a two-dimensional raster.")
    valid = np.isfinite(raster.astype(float))
    if nodata_mask is not None:
        mask = np.asarray(nodata_mask, dtype=bool)
        if mask.shape != raster.shape:
            raise ValueError("nodata_mask shape must match raster shape.")
        valid &= mask
    crs = CRS.from_epsg(spec.crs_epsg)
    transform = spec.transform
    if crs.is_geographic:
        if transform.b != 0 or transform.d != 0:
            raise ValueError("Rotated geographic rasters require per-cell geodesic area calculation.")
        geod = crs.get_geod()
        area_per_row = []
        for row in range(raster.shape[0]):
            west, north = transform @ (0, row)
            east, south = transform @ (1, row + 1)
            area, _ = geod.polygon_area_perimeter([west, east, east, west], [north, north, south, south])
            area_per_row.append(abs(area))
        cell_area = np.asarray(area_per_row)[:, None]
        method = "ellipsoidal_geodesic"
    elif crs.is_projected:
        conversion = crs.axis_info[0].unit_conversion_factor
        cell_area = abs(transform.a * transform.e - transform.b * transform.d) * conversion**2
        method = "planar_projected"
    else:
        raise ValueError("Area statistics require a geographic or projected CRS.")
    valid_area_m2 = float(np.sum(valid * cell_area))
    summary = {
        "valid_cells": int(np.count_nonzero(valid)),
        "valid_area_m2": valid_area_m2,
        "valid_area_ha": valid_area_m2 / 10_000,
        "valid_area_km2": valid_area_m2 / 1_000_000,
        "method": method,
        "crs": crs.to_string(),
    }
    # Only integer/bool rasters represent discrete classes. Continuous model
    # scores are never discretized here or given invented class thresholds.
    if np.issubdtype(raster.dtype, np.bool_) or np.issubdtype(raster.dtype, np.integer):
        classes = np.unique(raster[valid])
        if classes.size > 256:
            raise ValueError("Categorical area statistics exceed the supported class inventory.")
        summary["class_areas"] = []
        for value in classes:
            selected = valid & (raster == value)
            area_m2 = float(np.sum(selected * cell_area))
            summary["class_areas"].append({
                "class_value": int(value), "cells": int(np.count_nonzero(selected)),
                "area_m2": area_m2, "area_ha": area_m2 / 10_000,
                "area_km2": area_m2 / 1_000_000,
                "percent_of_valid": 100 * area_m2 / valid_area_m2 if valid_area_m2 else 0.0,
            })
    if (np.issubdtype(raster.dtype, np.bool_) or np.issubdtype(raster.dtype, np.integer)) and np.all((raster[valid] == 0) | (raster[valid] == 1)):
        flooded = valid & (raster.astype(float) == 1)
        flooded_area_m2 = float(np.sum(flooded * cell_area))
        summary["flooded_area_m2"] = flooded_area_m2
        summary["flooded_area_ha"] = flooded_area_m2 / 10_000
        summary["flooded_area_km2"] = flooded_area_m2 / 1_000_000
        summary["flooded_percent_of_valid"] = 100 * flooded_area_m2 / valid_area_m2 if valid_area_m2 else 0.0
    return summary
