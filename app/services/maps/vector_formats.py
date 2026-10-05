"""Loss-aware protected vector exports from existing WGS84 GeoJSON only."""
from __future__ import annotations

import json
import re
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape
from shapely import get_coordinates

from app.services.reporting.evidence import verified_artifact

KML = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML)
SUPPORTED = {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}


def _text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) if isinstance(value, (dict, list)) else str(value)


def _kml_geometry(parent, geometry):
    name = geometry.geom_type
    if name.startswith("Multi"):
        multi = ET.SubElement(parent, f"{{{KML}}}MultiGeometry")
        for part in geometry.geoms:
            _kml_geometry(multi, part)
        return
    node = ET.SubElement(parent, f"{{{KML}}}" + name)
    if name == "Polygon":
        rings = [("outerBoundaryIs", geometry.exterior)] + [("innerBoundaryIs", ring) for ring in geometry.interiors]
        for role, ring in rings:
            boundary = ET.SubElement(node, f"{{{KML}}}" + role)
            linear = ET.SubElement(boundary, f"{{{KML}}}LinearRing")
            ET.SubElement(linear, f"{{{KML}}}coordinates").text = " ".join(
                ",".join(format(value, ".17g") for value in coordinate) for coordinate in ring.coords)
    else:
        ET.SubElement(node, f"{{{KML}}}coordinates").text = " ".join(
            ",".join(format(value, ".17g") for value in coordinate) for coordinate in geometry.coords)


def export_vector_formats(directory: Path, name: str, entry: dict, provenance: dict) -> dict[str, tuple[Path, dict]]:
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError("Derived vector artifact name is invalid")
    path = verified_artifact(directory, entry)
    metadata = entry.get("gis_metadata") or {}
    if metadata.get("crs") != "EPSG:4326":
        raise ValueError("Derived vector formats require explicit WGS84 GeoJSON")
    collection = json.loads(path.read_text(encoding="utf-8"))
    if collection.get("type") != "FeatureCollection" or not isinstance(collection.get("features"), list):
        raise ValueError("Derived vector source is not a FeatureCollection")
    features = collection["features"]
    geometries, properties = [], []
    for feature in features:
        geometry = shape(feature["geometry"])
        if (geometry.geom_type not in SUPPORTED or geometry.is_empty or not geometry.is_valid
                or not np.isfinite(get_coordinates(geometry, include_z=geometry.has_z)).all()
                or not np.isfinite(geometry.bounds).all() or geometry.bounds[0] < -180
                or geometry.bounds[2] > 180 or geometry.bounds[1] < -90 or geometry.bounds[3] > 90):
            raise ValueError("Derived vector source geometry is invalid/unsupported")
        values = feature.get("properties") or {}
        if not isinstance(values, dict):
            raise ValueError("Vector properties must be an object")
        json.dumps(values, allow_nan=False)
        geometries.append(geometry)
        properties.append(values)
    families = {geometry.geom_type.removeprefix("Multi") for geometry in geometries}
    fields = sorted({key for record in properties for key in record})
    if any(key.lower() in {"geometry", "fid"} for key in fields):
        raise ValueError("Vector property conflicts with a reserved GeoPackage geometry/identity field")
    # GPKG preserves all field names; structured attributes use declared JSON encoding.
    records = [{key: (_text(record[key]) if isinstance(record.get(key), (dict, list)) else record.get(key)) for key in fields} for record in properties]
    frame = gpd.GeoDataFrame(pd.DataFrame(records, columns=fields), geometry=geometries, crs="EPSG:4326")
    gpkg = directory / (name + ".gpkg")
    frame.to_file(gpkg, driver="GPKG", layer="features", engine="pyogrio", index=False,
        geometry_type=("Unknown" if geometries else "Polygon"))
    reread = gpd.read_file(gpkg)
    if len(reread) != len(frame) or reread.crs.to_epsg() != 4326 or any(not left.equals_exact(right, 1e-10) for left, right in zip(geometries, reread.geometry)):
        raise ValueError("GeoPackage geometry/CRS round trip changed")
    for index, record in enumerate(records):
        for key, expected in record.items():
            if key not in reread:
                raise ValueError("GeoPackage attribute field disappeared")
            actual = reread.iloc[index][key]
            if hasattr(actual, "item"):
                actual = actual.item()
            if (expected is None and not pd.isna(actual)) or (expected is not None and (pd.isna(actual) or actual != expected)):
                raise ValueError("GeoPackage attribute round trip changed")
    # DBF uses explicit mapped text attributes, with complete originals retained
    # in the protected sidecar; no silent truncation or integer precision loss.
    field_map = {f"f{index:07d}": key for index, key in enumerate(fields)}
    dbf_records = [{short: _text(record[original]) if original in record and record[original] is not None else ""
                   for short, original in field_map.items()} for record in properties]
    if any(len(value.encode("utf-8")) > 254 for record in dbf_records for value in record.values()):
        # DBF has a hard width limit. Explicit sidecar reference replaces a long
        # display value; full text is never discarded or presented as complete.
        for index, record in enumerate(dbf_records):
            for field, value in record.items():
                if len(value.encode("utf-8")) > 254:
                    record[field] = f"[full value: attributes.json feature {index} mapped field {field}]"
    shapefile_zip = directory / (name + "-shapefile.zip")
    with tempfile.TemporaryDirectory(prefix="nova-vector-") as temporary:
        temporary = Path(temporary)
        layers = {}
        # A Shapefile layer has one geometry family. Mixed inventories retain
        # every feature in explicitly separate layers, with source-order mapping.
        for family in sorted(families or {"Polygon"}):
            indices = [index for index, geometry in enumerate(geometries)
                       if geometry.geom_type.removeprefix("Multi") == family]
            layer_name = "features" if len(families) <= 1 else family.lower()
            selected = [geometries[index] for index in indices]
            short_frame = gpd.GeoDataFrame(pd.DataFrame([dbf_records[index] for index in indices], columns=list(field_map)),
                geometry=selected, crs="EPSG:4326")
            shp = temporary / (layer_name + ".shp")
            short_frame.to_file(shp, driver="ESRI Shapefile", engine="pyogrio", index=False, encoding="UTF-8",
                geometry_type=("Unknown" if selected else "Polygon"))
            reread = gpd.read_file(shp)
            if len(reread) != len(selected) or reread.crs.to_epsg() != 4326 or any(not left.equals(right) for left, right in zip(selected, reread.geometry)):
                raise ValueError("Shapefile geometry/CRS round trip changed")
            layers[layer_name] = {"geometry_family": family, "source_feature_indices": indices}
        sidecar = {"source_sha256": entry["checksum_sha256"], "field_map": field_map,
                   "attribute_policy": "mapped DBF text; full typed properties in this sidecar by source feature order",
                   "layers": layers, "properties": properties, "gis_metadata": metadata, "provenance": provenance}
        (temporary / "attributes.json").write_text(json.dumps(sidecar, ensure_ascii=False, default=str), encoding="utf-8")
        with zipfile.ZipFile(shapefile_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(temporary.iterdir()):
                archive.write(file, file.name)
    kml = directory / (name + ".kml")
    root = ET.Element(f"{{{KML}}}kml")
    document = ET.SubElement(root, f"{{{KML}}}Document")
    ET.SubElement(document, f"{{{KML}}}name").text = name
    ET.SubElement(document, f"{{{KML}}}description").text = _text({"gis_metadata": metadata, "source_sha256": entry["checksum_sha256"], "provenance": provenance})
    for geometry, record in zip(geometries, properties):
        placemark = ET.SubElement(document, f"{{{KML}}}Placemark")
        extended = ET.SubElement(placemark, f"{{{KML}}}ExtendedData")
        for key, value in record.items():
            data = ET.SubElement(extended, f"{{{KML}}}Data", name=key)
            ET.SubElement(data, f"{{{KML}}}value").text = _text(value)
        _kml_geometry(placemark, geometry)
    ET.ElementTree(root).write(kml, encoding="utf-8", xml_declaration=True)
    ET.parse(kml)  # Reject XML-incompatible source attribute characters.
    derived = {**metadata, "source_artifact_sha256": entry["checksum_sha256"], "geometry_policy": "source geometry preserved in WGS84; no raster resampling/polygon simplification",
               "attribute_encoding": "structured fields as JSON strings in GPKG/KML; mapped DBF text with complete typed attributes sidecar"}
    return {"gpkg": (gpkg, derived), "kml": (kml, derived), "shapefile_zip": (shapefile_zip, {**derived, "field_map": field_map, "layers": layers})}
