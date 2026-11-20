"""FRRIS v1.1 boundary sources (docs/FRRIS_ADMIN_LEVEL_EXPOSURE_PLAN.md §3; owner decisions 2026-11-20).

* L2 districts: geoBoundaries gbOpen TZA ADM2 (NBS / UN OCHA ROSA, CC BY 3.0 IGO), pinned release file, checksum-verified.
* L1 regions: built by grouping those districts with app/reference_data/boundaries/tza/district_region.csv (exact nesting,
  one licence). The table is used only once the owner has approved it (manifest status "APPROVED ..."). The 2015 OSM
  regions layer is never used.
* L3 wards: only the client's NBS ward boundaries, approved through the reviewed-dataset flow; otherwise
  "Ward boundaries not yet provided". Never filled from geoBoundaries ADM3, OSM or any other source.
"""
from __future__ import annotations

import csv
import functools
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from shapely.geometry import shape
from shapely.ops import unary_union

from app.services.firris.admin_units import WARDS_NOT_PROVIDED, BoundaryUnits, NotProvided, Unit

MANIFESTS = Path(__file__).resolve().parents[2] / "reference_data" / "boundaries"
REGIONS_PENDING = ("Region totals are not shown yet: the district-to-region table is waiting for the owner's approval.")
FILE_UNAVAILABLE = "The pinned boundary file for this level is not available on the server; this level is not shown."


def clean_name(name: str) -> str:
    """Display name: whitespace collapsed (the source has double spaces); the source name is kept in provenance."""
    return re.sub(r"\s+", " ", name).strip()


@functools.lru_cache(maxsize=4)
def manifest(country: str = "tza") -> dict[str, Any]:
    return json.loads((MANIFESTS / country / "manifest.json").read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=4)
def _features(path: str, sha256: str) -> list[dict]:
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise FileNotFoundError(f"{path} does not match its pinned SHA-256")
    return json.loads(data)["features"]


def _provenance(entry: dict, country_manifest: dict, **extra) -> dict[str, Any]:
    return {"dataset": "geoBoundaries", "release": country_manifest["release"], "boundaryID": entry["boundaryID"],
            "release_type": entry["release_type"], "year_represented": entry["year_represented"], "source": entry["source"],
            "licence": entry["licence"], "url": entry["url"], "sha256": entry["sha256"],
            "citation": country_manifest["citation"], **extra}


def district_region_table(country: str = "tza") -> dict[str, str]:
    with (MANIFESTS / country / "district_region.csv").open(encoding="utf-8") as handle:
        return {row["district_shapeID"]: row["region"] for row in csv.DictReader(handle)}


def regions_approved(country: str = "tza") -> bool:
    return str(manifest(country)["district_region_table"]["status"]).upper().startswith("APPROVED")


class GeoBoundariesDistricts:
    level = "L2"

    def __init__(self, reference_dir: str | Path, country: str = "tza"):
        self.reference_dir, self.country = Path(reference_dir), country

    def all_units(self) -> list[Unit]:
        country_manifest = manifest(self.country)
        entry = country_manifest["files"]["districts"]
        features = _features(str(self.reference_dir / "boundaries" / self.country / entry["file"]), entry["sha256"])
        regions = district_region_table(self.country) if regions_approved(self.country) else {}
        return [Unit(id=f["properties"]["shapeID"], name=clean_name(f["properties"]["shapeName"]), level="L2",
                     geometry=shape(f["geometry"]), parent=regions.get(f["properties"]["shapeID"])) for f in features]

    def units(self, aoi_geometry: dict) -> BoundaryUnits | NotProvided:
        country_manifest = manifest(self.country)
        entry = country_manifest["files"]["districts"]
        try:
            units = self.all_units()
        except (FileNotFoundError, OSError):
            return NotProvided("L2", FILE_UNAVAILABLE, _provenance(entry, country_manifest))
        aoi = shape(aoi_geometry)
        return BoundaryUnits("L2", [u for u in units if u.geometry.intersects(aoi)], _provenance(entry, country_manifest))


class GroupedRegions:
    """L1 regions as the union of their districts (exact nesting with L2)."""
    level = "L1"

    def __init__(self, districts: GeoBoundariesDistricts):
        self.districts = districts

    def units(self, aoi_geometry: dict) -> BoundaryUnits | NotProvided:
        country = self.districts.country
        country_manifest = manifest(country)
        table_entry = country_manifest["district_region_table"]
        provenance = _provenance(country_manifest["files"]["districts"], country_manifest,
                                 grouping={"table": table_entry["file"], "method": table_entry["method"],
                                           "status": table_entry["status"],
                                           "region_lookup": _provenance(country_manifest["files"]["region_lookup"], country_manifest)})
        if not regions_approved(country):
            return NotProvided("L1", REGIONS_PENDING, provenance)
        try:
            districts = self.districts.all_units()
        except (FileNotFoundError, OSError):
            return NotProvided("L1", FILE_UNAVAILABLE, provenance)
        grouped: dict[str, list] = {}
        for unit in districts:
            if unit.parent:
                grouped.setdefault(unit.parent, []).append(unit.geometry.buffer(0))
        aoi = shape(aoi_geometry)
        units = [Unit(id=f"region:{name}", name=name, level="L1", geometry=unary_union(parts))
                 for name, parts in sorted(grouped.items())]
        return BoundaryUnits("L1", [u for u in units if u.geometry.intersects(aoi)], provenance)


class ReviewedWards:
    """L3 wards from the organisation's approved administrative-boundary dataset (client NBS wards) only."""
    level = "L3"

    def __init__(self, db, project_id: uuid.UUID):
        self.db, self.project_id = db, project_id

    def units(self, aoi_geometry: dict) -> BoundaryUnits | NotProvided:
        from app.services.source_data.boundaries import approved_boundary_sources, boundary_features
        aoi = shape(aoi_geometry)
        for source in approved_boundary_sources(self.db, self.project_id):
            wards = [f for f in boundary_features(source) if str(f["properties"].get("level", "")).lower() == "ward"]
            if not wards:
                continue
            units = [Unit(id=str(f["properties"]["spatial_unit_id"]), name=clean_name(str(f["properties"]["name"])),
                          level="L3", geometry=shape(f["geometry"]), code=str(f["properties"]["spatial_unit_id"]))
                     for f in wards]
            provenance = {"dataset": "client-supplied NBS ward boundaries (reviewed dataset)",
                          "dataset_id": str(source.dataset.id), "source_id": source.manifest.source_id,
                          "sha256": source.manifest.sha256.lower(), "licence": source.manifest.licence.model_dump(),
                          "reviewed_at": source.evidence.get("reviewed_at")}
            return BoundaryUnits("L3", [u for u in units if u.geometry.intersects(aoi)], provenance)
        return NotProvided("L3", WARDS_NOT_PROVIDED)
