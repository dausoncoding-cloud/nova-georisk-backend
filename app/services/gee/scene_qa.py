"""Bounded per-scene metadata QA before compositing or downloading pixels."""
from datetime import datetime, timezone
import math

from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely.geometry import shape
from shapely.ops import unary_union

MAX_SCENES = 500


def inspect_collection(collection, *, sensor, period, aoi, required_bands, max_cloud=100, collection_id=None):
    count = int(collection.size().getInfo())
    if not 1 <= count <= MAX_SCENES:
        raise ValueError("Required collection is empty or exceeds bounded per-scene QA limit")
    images = collection.toList(count).getInfo()
    if not isinstance(images, list) or len(images) != count:
        raise ValueError("Per-scene QA metadata is incomplete")
    records, footprints = [], []
    identifiers = set()
    for image in images:
        if not isinstance(image,dict) or not isinstance(image.get("properties"),dict):
            raise ValueError("Scene metadata/properties are malformed")
        properties = image["properties"]
        identifier = image.get("id")
        timestamp = properties.get("system:time_start")
        if not isinstance(identifier,str) or not identifier or identifier in identifiers or isinstance(timestamp,bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise ValueError("Scene identity/acquisition provenance is missing or duplicated")
        if collection_id is not None and not identifier.startswith(collection_id+"/"):
            raise ValueError("Scene identity is outside the selected source collection")
        identifiers.add(identifier)
        try:
            acquisition=datetime.fromtimestamp(timestamp/1000,timezone.utc)
        except (OSError,OverflowError,ValueError) as exc:
            raise ValueError("Scene acquisition timestamp is invalid") from exc
        acquired = acquisition.date().isoformat()
        if not period["start"] <= acquired < period["end"]:
            raise ValueError("Scene acquisition is outside requested period")
        native=image.get("bands", [])
        if not isinstance(native,list) or any(not isinstance(band,dict) or not band.get("id") for band in native):
            raise ValueError("Scene band identities are invalid")
        bands = {band["id"]: band for band in native}
        if len(bands)!=len(native): raise ValueError("Scene band identities are duplicated")
        if not set(required_bands).issubset(bands):
            raise ValueError("Scene lacks required sensor bands for FIRRIS")
        projections = {}
        for name in required_bands:
            band = bands[name]
            try:
                crs = CRS.from_user_input(band["crs"])
                grid = band["crs_transform"]
                if len(grid) != 6 or not all(math.isfinite(v) for v in grid) or grid[0] <= 0 or grid[4] >= 0 or grid[1] or grid[3]:
                    raise ValueError()
                if not (crs.is_projected or crs.is_geographic):
                    raise ValueError()
            except (KeyError, TypeError, ValueError, CRSError) as exc:
                raise ValueError("Scene native CRS/grid metadata is invalid") from exc
            if sensor == "Sentinel-2":
                expected_scale = 20 if name in {"B11", "SCL"} else 10
                if not crs.is_projected or len(crs.axis_info) < 2 or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in crs.axis_info[:2]):
                    raise ValueError("Optical native projection must use metre units")
                if not math.isclose(grid[0], expected_scale, rel_tol=1e-6) or not math.isclose(-grid[4], expected_scale, rel_tol=1e-6):
                    raise ValueError("Optical native band scale differs from registered sensor policy")
            projections[name] = {"crs": crs.to_string(), "transform": grid}
        if sensor == "Sentinel-2" and len({record["crs"] for record in projections.values()}) != 1:
            raise ValueError("Optical scene bands do not share a native CRS")
        try:
            footprint_geometry = properties["system:footprint"]
            if footprint_geometry.get("type") == "LinearRing":
                footprint_geometry = {"type": "Polygon", "coordinates": [footprint_geometry["coordinates"]]}
            footprint = shape(footprint_geometry)
            if footprint.is_empty or not footprint.is_valid or not footprint.intersects(shape(aoi)):
                raise ValueError()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Scene footprint is missing or invalid") from exc
        footprints.append(footprint)
        checks = {}
        if sensor == "Sentinel-2":
            cloud = properties.get("CLOUDY_PIXEL_PERCENTAGE")
            degraded = properties.get("DEGRADED_MSI_DATA_PERCENTAGE")
            tile = properties.get("MGRS_TILE")
            if not tile or any(not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 100 for value in (cloud, degraded)):
                raise ValueError("Optical scene quality/tile metadata is missing")
            if cloud > max_cloud or degraded > 0:
                raise ValueError("Optical scene cloud/sensor quality requirements are unmet")
            checks = {"tile": tile, "cloud_pct": cloud, "degraded_msi_pct": degraded,
                      "pixel_fault_check": "SCL no-data/defective pixels masked"}
        elif sensor == "Sentinel-1":
            if (properties.get("instrumentMode") != "IW" or properties.get("orbitProperties_pass") != "ASCENDING"
                    or "VV" not in properties.get("transmitterReceiverPolarisation", [])
                    or not isinstance(properties.get("relativeOrbitNumber_start"), int)):
                raise ValueError("SAR sensor/mode/polarization/orbit QA requirements are unmet")
            checks = {"relative_orbit": properties["relativeOrbitNumber_start"], "pass": "ASCENDING",
                      "sensor_fault_check": "finite backscatter and provider mask; no independent hardware diagnostics available"}
        records.append({"scene_id": identifier, "collection_id": collection_id, "acquired_at": acquired, "acquired_at_utc": acquisition.isoformat(), **metadata_identity(image), "native_bands": projections,
                        "status": "passed", "footprint": properties["system:footprint"],
                        "qa_scope": "provider metadata and required bands/grid; pixel mask applied before composite", **checks})
    missing = shape(aoi).difference(unary_union(footprints))
    if not missing.is_empty and missing.area > shape(aoi).area * 1e-8:
        raise ValueError("Missing scene tiles: collection footprints do not cover AOI")
    return {"scene_count": count, "scenes": records, "footprint_coverage": "complete",
            "missing_tile_policy": "reject uncovered AOI; pixel gaps separately assessed"}


def metadata_identity(metadata):
    """Hash metadata actually returned by the provider, not unavailable source pixels."""
    import hashlib
    import json
    encoded=json.dumps(metadata,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    properties=metadata.get('properties') or {}
    return {'provider_metadata':json.loads(encoded),'metadata_sha256':hashlib.sha256(encoded).hexdigest(),
            'provider_version':properties.get('system:version'),
            'provider_source_byte_sha256':None,
            'source_byte_checksum_availability':'unavailable; provider scene metadata does not expose original source-byte checksums'}


def inspect_static_image(image, *, asset_id, required_band):
    """A named provider image is rechecked before deriving terrain/water products."""
    metadata=image.getInfo()
    if not isinstance(metadata,dict) or metadata.get('id')!=asset_id:
        raise ValueError('Static source identity differs from the selected provider asset')
    bands=metadata.get('bands')
    if not isinstance(bands,list) or any(not isinstance(band,dict) or not band.get('id') for band in bands) or len({band.get('id') for band in bands})!=len(bands):
        raise ValueError('Static source band identity is missing or duplicated')
    band=next((band for band in bands if band.get('id')==required_band),None)
    if band is None: raise ValueError('Static source required band is unavailable')
    from rasterio import Affine
    from app.services.gee.firris_contracts import validate_grid
    try: validate_grid(band['crs'],Affine(*band['crs_transform']))
    except (KeyError,TypeError,ValueError) as exc: raise ValueError('Static source native CRS/grid is invalid') from exc
    return {'asset_id':asset_id,'native_band':band,'status':'passed',**metadata_identity(metadata),
            'temporal_coverage':'static provider product; event observation time not inferred'}
