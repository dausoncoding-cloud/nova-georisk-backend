"""Bounded per-scene metadata QA before compositing or downloading pixels."""
from datetime import datetime, timezone
import math

from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely.geometry import shape
from shapely.ops import unary_union

MAX_SCENES = 500


def inspect_collection(collection, *, sensor, period, aoi, required_bands, max_cloud=100):
    count = int(collection.size().getInfo())
    if not 1 <= count <= MAX_SCENES:
        raise ValueError("Required collection is empty or exceeds bounded per-scene QA limit")
    images = collection.toList(count).getInfo()
    if not isinstance(images, list) or len(images) != count:
        raise ValueError("Per-scene QA metadata is incomplete")
    records, footprints = [], []
    identifiers = set()
    for image in images:
        properties = image.get("properties", {})
        identifier = image.get("id")
        timestamp = properties.get("system:time_start")
        if not identifier or identifier in identifiers or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise ValueError("Scene identity/acquisition provenance is missing or duplicated")
        identifiers.add(identifier)
        acquired = datetime.fromtimestamp(timestamp / 1000, timezone.utc).date().isoformat()
        if not period["start"] <= acquired < period["end"]:
            raise ValueError("Scene acquisition is outside requested period")
        bands = {band["id"]: band for band in image.get("bands", [])}
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
        records.append({"scene_id": identifier, "acquired_at": acquired, "native_bands": projections,
                        "status": "passed", "footprint": properties["system:footprint"],
                        "qa_scope": "provider metadata and required bands/grid; pixel mask applied before composite", **checks})
    missing = shape(aoi).difference(unary_union(footprints))
    if not missing.is_empty and missing.area > shape(aoi).area * 1e-8:
        raise ValueError("Missing scene tiles: collection footprints do not cover AOI")
    return {"scene_count": count, "scenes": records, "footprint_coverage": "complete",
            "missing_tile_policy": "reject uncovered AOI; pixel gaps separately assessed"}
