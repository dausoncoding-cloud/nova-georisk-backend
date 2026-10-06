"""Structural ingestion gates; no imputation, reprojection, or scientific certification."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from datetime import datetime

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import transform_bounds
from shapely.geometry import shape
from shapely.errors import GEOSException

from app.schemas.source_data import SourceDatasetManifest, SourceDatasetValidation
from app.services.source_data.catalogue import get_profile


class SourceDataValidationError(ValueError):
    pass


MAX_BYTES = 100 * 1024 * 1024
MAX_RECORDS = 100_000


def _fail(message: str) -> None:
    raise SourceDataValidationError(message)


def _timestamp(value: str, manifest: SourceDatasetManifest) -> None:
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        _fail("Invalid observation timestamp")
    if observed.tzinfo is None or not manifest.temporal_coverage.start <= observed <= manifest.temporal_coverage.end:
        _fail("Observation timestamp is outside declared timezone-aware coverage")


def _field(value: object, kind: str, manifest: SourceDatasetManifest) -> None:
    if value is None or value == "":
        _fail("Required source field is blank")
    if kind == "string":
        if not isinstance(value, str) or not value.strip():
            _fail("Required string field is invalid")
    elif kind == "datetime":
        _timestamp(value, manifest)
    elif kind == "quality_flag":
        if value != "valid":
            _fail("Only quality_flag=valid observations may be ingested")
    else:
        try:
            number = float(value)
        except (ValueError, TypeError):
            _fail("Required numeric field is invalid")
        if not math.isfinite(number):
            _fail("Non-finite source value")
        if kind == "longitude" and not -180 <= number <= 180:
            _fail("Longitude outside WGS84 range")
        if kind == "latitude" and not -90 <= number <= 90:
            _fail("Latitude outside WGS84 range")
        if kind == "nonnegative_number" and number < 0:
            _fail("Negative value for nonnegative field")
        if kind in ("positive_number", "positive_integer") and number <= 0:
            _fail("Non-positive required value")
        if kind == "positive_integer" and not number.is_integer():
            _fail("Sample count must be an integer")


def _properties(properties: dict, profile: dict, manifest: SourceDatasetManifest) -> None:
    required = profile["required_fields"]
    if not isinstance(properties, dict) or not set(required).issubset(properties):
        _fail("Required source fields are missing")
    if set(properties) != set(required):
        _fail("Undeclared source fields are not accepted")
    for key, kind in required.items():
        _field(properties[key], kind, manifest)
    if "start_at" in properties and "end_at" in properties:
        start = datetime.fromisoformat(properties["start_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(properties["end_at"].replace("Z", "+00:00"))
        if end < start:
            _fail("Event end precedes start")


def _csv(data: bytes, profile: dict, manifest: SourceDatasetManifest) -> tuple[int, list[float] | None]:
    try:
        stream = io.StringIO(data.decode("utf-8-sig", errors="strict"), newline="")
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
            _fail("CSV requires a unique header")
        if set(reader.fieldnames) != set(profile["required_fields"]):
            _fail("CSV fields do not match catalogue")
        count = 0
        seen: set[tuple] = set()
        indicators_by_unit: dict[str, set[str]] = {}
        bounds = [180.0, 90.0, -180.0, -90.0] if "longitude" in reader.fieldnames else None
        for row in reader:
            count += 1
            if count > MAX_RECORDS:
                _fail("Source record limit exceeded")
            _properties(row, profile, manifest)
            if bounds is not None:
                lon, lat = float(row["longitude"]), float(row["latitude"])
                bounds = [min(bounds[0], lon), min(bounds[1], lat), max(bounds[2], lon), max(bounds[3], lat)]
            if manifest.category == "flood_predictor_observations":
                definition = manifest.predictor_definitions.get(row["variable"])
                if definition is None or definition.unit != row["unit"]:
                    _fail("Predictor variable or unit differs from its reviewed definition")
                unique_key = (row["sample_id"], row["variable"])
            elif "indicator_key" in row:
                key, unit = row["indicator_key"], row["unit"]
                if key not in profile["required_indicators"] or unit != manifest.indicator_units[key]:
                    _fail("Undeclared indicator or mismatched indicator unit")
                indicators_by_unit.setdefault(row["spatial_unit_id"], set()).add(key)
                unique_key = (row["spatial_unit_id"], key)
            else:
                unique_key = (row.get("station_id", row.get("section_id")), row.get("observed_at"))
            if unique_key in seen:
                _fail("Duplicate source observation")
            seen.add(unique_key)
        if count == 0:
            _fail("Empty source dataset")
        if profile.get("required_indicators") and any(keys != set(profile["required_indicators"]) for keys in indicators_by_unit.values()):
            _fail("Incomplete indicator set for spatial unit")
        return count, bounds
    except (UnicodeDecodeError, csv.Error) as exc:
        raise SourceDataValidationError("Invalid UTF-8 CSV source") from exc


def _geojson(data: bytes, profile: dict, manifest: SourceDatasetManifest) -> tuple[int, list[float]]:
    try:
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceDataValidationError("Invalid GeoJSON source") from exc
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        _fail("GeoJSON must be a FeatureCollection")
    if "crs" in document:
        _fail("GeoJSON CRS member is not accepted; use RFC 7946 WGS84 coordinates")
    features = document.get("features")
    if not isinstance(features, list) or not 0 < len(features) <= MAX_RECORDS:
        _fail("GeoJSON requires a nonempty bounded feature collection")
    bounds = [180.0, 90.0, -180.0, -90.0]
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            _fail("Invalid GeoJSON feature")
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in profile["geometry"]:
            _fail("Wrong geometry type for source category")
        try:
            geom = shape(geometry)
        except (ValueError, TypeError, KeyError, GEOSException) as exc:
            raise SourceDataValidationError("Invalid source geometry") from exc
        if geom.is_empty or not geom.is_valid:
            _fail("Empty or invalid source geometry")
        left, bottom, right, top = geom.bounds
        if not (-180 <= left <= right <= 180 and -90 <= bottom <= top <= 90):
            _fail("Geometry lies outside WGS84 coordinate range")
        bounds = [min(bounds[0], left), min(bounds[1], bottom), max(bounds[2], right), max(bounds[3], top)]
        _properties(feature.get("properties"), profile, manifest)
    return len(features), bounds


def _geotiff(data: bytes, manifest: SourceDatasetManifest) -> tuple[int, list[float]]:
    try:
        with MemoryFile(data) as memory, memory.open() as src:
            if src.driver != "GTiff" or src.count != 1 or src.crs is None or src.crs.to_string() != manifest.crs:
                _fail("GeoTIFF driver, band count or CRS mismatch")
            if src.nodata is None or src.nodata != manifest.nodata:
                _fail("GeoTIFF nodata mismatch")
            if src.width * src.height > 25_000_000 or src.width == 0 or src.height == 0:
                _fail("GeoTIFF cell limit exceeded")
            if src.transform.b != 0 or src.transform.d != 0 or src.transform.a <= 0 or src.transform.e >= 0:
                _fail("GeoTIFF requires north-up affine georeferencing")
            expected_unit = "degree" if src.crs.is_geographic else "m"
            if src.crs.is_projected and not math.isclose(src.crs.linear_units_factor[1], 1.0, rel_tol=1e-9):
                _fail("Projected raster CRS must use metres")
            if manifest.spatial_resolution.unit != expected_unit:
                _fail("Raster resolution unit disagrees with CRS")
            if not math.isclose(abs(src.transform.a), manifest.spatial_resolution.x, rel_tol=1e-6) or not math.isclose(abs(src.transform.e), manifest.spatial_resolution.y, rel_tol=1e-6):
                _fail("Raster resolution disagrees with manifest")
            arr = src.read(1, masked=True)
            values = arr.compressed()
            if not len(values) or not np.isfinite(values).all():
                _fail("Raster has no finite valid observations")
            category = manifest.category
            if category in {"inundation_time_slice", "annual_inundation_observation", "cropland_fraction"}:
                if category in {"inundation_time_slice", "annual_inundation_observation"} and not np.isin(values, [0, 1]).all():
                    _fail("Inundation raster must be binary")
                if category == "cropland_fraction" and ((values < 0) | (values > 1)).any():
                    _fail("Cropland fraction must be between zero and one")
            elif category in {"soil_permeability", "population_density", "livestock_density", "hydraulic_model_velocity"} and (values < 0).any():
                _fail("Negative raster values are invalid for this category")
            elif category == "soil_texture_classes":
                if not np.equal(values, np.floor(values)).all() or not set(map(str, np.unique(values.astype(int)))).issubset(manifest.soil_scoring_policy.classes):
                    _fail("Soil texture codes are absent from the sourced five-class policy")
            elif category == "land_cover":
                if not np.equal(values, np.floor(values)).all() or not set(map(str, np.unique(values.astype(int)))).issubset(manifest.class_scheme):
                    _fail("Land-cover codes are absent from the declared class scheme")
            b = src.bounds
            return int(len(values)), [b.left, b.bottom, b.right, b.top]
    except (rasterio.errors.RasterioError, OSError) as exc:
        raise SourceDataValidationError("Invalid GeoTIFF source") from exc


def validate_source_data(manifest: SourceDatasetManifest, data: bytes, filename: str) -> SourceDatasetValidation:
    profile = get_profile(manifest.category)
    extension = {"csv": ".csv", "geojson": ".geojson", "geotiff": ".tif"}[profile["format"]]
    if not filename.lower().endswith(extension) or not 0 < len(data) <= MAX_BYTES:
        _fail("Source extension or byte size is invalid")
    digest = hashlib.sha256(data).hexdigest()
    if digest.lower() != manifest.sha256.lower():
        _fail("Source checksum does not match manifest")
    count, bounds = {"csv": _csv, "geojson": _geojson}.get(profile["format"], lambda d, p, m: _geotiff(d, m))(data, profile, manifest)
    if bounds is not None:
        wgs84_bounds = transform_bounds(manifest.crs, "EPSG:4326", *bounds, densify_pts=21) if profile["format"] == "geotiff" else bounds
        coverage = manifest.geographic_coverage
        if not (coverage.west <= wgs84_bounds[0] <= wgs84_bounds[2] <= coverage.east
                and coverage.south <= wgs84_bounds[1] <= wgs84_bounds[3] <= coverage.north):
            _fail("Observed source footprint exceeds declared geographic coverage")
    return SourceDatasetValidation(category=manifest.category, format=profile["format"], record_count=count, bounds=bounds, sha256=digest)
