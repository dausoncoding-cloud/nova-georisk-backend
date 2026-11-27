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
from dataclasses import dataclass
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


def clean_name(name: str, country: str = "tza") -> str:
    """Display name: owner-approved spelling fixes, whitespace collapsed; the source name is kept in provenance."""
    fixes = manifest(country).get("display_name_fixes", {}) if country else {}
    return re.sub(r"\s+", " ", fixes.get(name, name)).strip()


def limitations(country: str = "tza") -> list[str]:
    return list(manifest(country).get("limitations", []))


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


@functools.lru_cache(maxsize=4)
def _district_units(path: str, sha256: str, country: str, approved: bool) -> tuple[Unit, ...]:
    features = _features(path, sha256)
    regions = district_region_table(country) if approved else {}
    return tuple(Unit(id=f["properties"]["shapeID"], name=clean_name(f["properties"]["shapeName"], country), level="L2",
                      geometry=shape(f["geometry"]).buffer(0), parent=regions.get(f["properties"]["shapeID"]),
                      source_name=f["properties"]["shapeName"]) for f in features)


class GeoBoundariesDistricts:
    level = "L2"

    def __init__(self, reference_dir: str | Path, country: str = "tza"):
        self.reference_dir, self.country = Path(reference_dir), country

    def all_units(self) -> list[Unit]:
        """Every district, parsed once per process (the pinned file is checksum-verified on first read)."""
        country_manifest = manifest(self.country)
        entry = country_manifest["files"]["districts"]
        return list(_district_units(str(self.reference_dir / "boundaries" / self.country / entry["file"]), entry["sha256"],
                                    self.country, regions_approved(self.country)))

    def units(self, aoi_geometry: dict) -> BoundaryUnits | NotProvided:
        country_manifest = manifest(self.country)
        entry = country_manifest["files"]["districts"]
        try:
            units = self.all_units()
        except (FileNotFoundError, OSError):
            return NotProvided("L2", FILE_UNAVAILABLE, _provenance(entry, country_manifest))
        aoi = shape(aoi_geometry)
        return BoundaryUnits("L2", [u for u in units if u.geometry.intersects(aoi)],
                             _provenance(entry, country_manifest, limitations=limitations(self.country)))


class GroupedRegions:
    """L1 regions as the union of their districts (exact nesting with L2)."""
    level = "L1"

    def __init__(self, districts: GeoBoundariesDistricts):
        self.districts = districts

    def units(self, aoi_geometry: dict) -> BoundaryUnits | NotProvided:
        country = self.districts.country
        country_manifest = manifest(country)
        table_entry = country_manifest["district_region_table"]
        provenance = _provenance(country_manifest["files"]["districts"], country_manifest, limitations=limitations(country),
                                 grouping={"table": table_entry["file"], "method": table_entry["method"],
                                           "status": table_entry["status"],
                                           "region_lookup": _provenance(country_manifest["files"]["region_lookup"], country_manifest)})
        if not regions_approved(country):
            return NotProvided("L1", REGIONS_PENDING, provenance)
        try:
            districts = self.districts.all_units()
        except (FileNotFoundError, OSError):
            return NotProvided("L1", FILE_UNAVAILABLE, provenance)
        aoi = shape(aoi_geometry)
        # Only the regions with a district touching the AOI are merged (the full region polygon is still needed for
        # the unit's share inside the AOI).
        touched = sorted({unit.parent for unit in districts if unit.parent and unit.geometry.intersects(aoi)})
        units = [Unit(id=f"region:{name}", name=name, level="L1",
                      geometry=unary_union([unit.geometry for unit in districts if unit.parent == name])) for name in touched]
        return BoundaryUnits("L1", units, provenance)


WARD_COLUMNS = ("spatial_unit_id", "name", "level", "council_short", "council_name", "region_name", "provenance_status")
WARD_INDEX_CACHE = 2  # approved ward versions kept parsed per worker process (one is the usual case)


@dataclass(frozen=True)
class WardIndex:
    units: tuple[Unit, ...]
    tree: object  # shapely STRtree over the unit geometries


@functools.lru_cache(maxsize=WARD_INDEX_CACHE)
def _ward_index(path: str, dataset_id: str, sha256: str) -> WardIndex | None:
    """Parse one approved, SHA-verified dataset version once (pyogrio; about 3 s and 50 MB for the 4,344 NBS wards).
    Keyed by dataset id and checksum, so a new version or changed bytes are never served from an old parse."""
    import pyogrio
    from shapely import STRtree
    available = set(pyogrio.read_info(path)["fields"])
    frame = pyogrio.read_dataframe(path, columns=[c for c in WARD_COLUMNS if c in available])
    frame = frame[frame["level"].astype(str).str.strip().str.lower() == "ward"]
    if frame.empty:
        return None
    units = tuple(Unit(id=str(row.spatial_unit_id), name=clean_name(str(row.name), country=""), source_name=str(row.name),
                       level="L3", geometry=row.geometry, code=str(row.spatial_unit_id),
                       parent=(str(getattr(row, "council_short", "") or "") or None))
                  for row in frame.itertuples(index=False))
    return WardIndex(units, STRtree([u.geometry for u in units]))


class ReviewedWards:
    """L3 wards from the project's approved administrative-boundary dataset (the client's ward layer) only.

    Every run applies the full approval and readiness checks and proves the bytes are the approved version (streamed
    SHA-256); the parsed wards and their spatial index are reused per dataset version, and only the wards touching the
    analysis area are returned.
    """
    level = "L3"

    def __init__(self, db, project_id: uuid.UUID):
        self.db, self.project_id = db, project_id

    def units(self, aoi_geometry: dict) -> BoundaryUnits | NotProvided:
        from app.services.source_data.boundaries import approved_boundary_sources
        aoi = shape(aoi_geometry)
        for source in approved_boundary_sources(self.db, self.project_id, verify_only=True):
            if source.manifest.category != "administrative_boundaries" or source.path is None:
                continue
            index = _ward_index(str(source.path), str(source.dataset.id), source.manifest.sha256.lower())
            if index is None:
                continue
            touching = [index.units[i] for i in index.tree.query(aoi, predicate="intersects")]
            touching.sort(key=lambda unit: unit.id)
            notes = ((source.dataset.metadata_json or {}).get("managed_version") or {}).get("descriptive_metadata") or {}
            provenance = {"dataset": "client-supplied ward boundaries (reviewed dataset)",
                          "dataset_id": str(source.dataset.id), "source_id": source.manifest.source_id,
                          "sha256": source.manifest.sha256.lower(), "licence": source.manifest.licence.model_dump(),
                          "provenance": source.manifest.provenance.model_dump(), "reviewed_at": source.evidence.get("reviewed_at"),
                          "provenance_statement": notes.get("provenance_statement"), "year": notes.get("year"),
                          "positional_accuracy": notes.get("positional_accuracy") or "Source positional accuracy: not stated.",
                          "licence_note": notes.get("licence")}
            return BoundaryUnits("L3", touching, provenance)
        return NotProvided("L3", WARDS_NOT_PROVIDED)


def resolve_admin_boundaries(aoi_geometry: dict, project_id, *, reference_dir: str | Path | None = None,
                             country: str = "tza") -> dict[str, BoundaryUnits | NotProvided]:
    """The three levels for one run, resolved before the workflow (the workflow itself has no database session).

    Regions and districts read the pinned files; wards read the project's approved boundary datasets in a short,
    read-only session. A failure at one level is that level's "not available" reason; it never stops the run.
    """
    import logging
    from app.core.config import get_settings
    log = logging.getLogger(__name__)
    districts = GeoBoundariesDistricts(reference_dir or get_settings().reference_data_dir, country)
    out: dict[str, BoundaryUnits | NotProvided] = {}
    for level, source in (("L1", GroupedRegions(districts)), ("L2", districts)):
        try:
            out[level] = source.units(aoi_geometry)
        except Exception:  # noqa: BLE001
            log.exception("Boundary level %s could not be read", level)
            out[level] = NotProvided(level, "The boundaries for this level could not be read for this run.")
    try:
        from sqlalchemy import text
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            db.execute(text("SET TRANSACTION READ ONLY"))
            out["L3"] = ReviewedWards(db, project_id).units(aoi_geometry)
        finally:
            db.rollback()
            db.close()
    except Exception:  # noqa: BLE001
        log.exception("Ward boundaries could not be read")
        out["L3"] = NotProvided("L3", "Ward boundaries could not be read for this run.")
    return out
