"""FRRIS v1.1 boundary sources: pinned districts, regions grouped from districts (after approval), wards only from the
client's reviewed dataset."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import box, mapping

from app.services.firris import boundary_sources as bs

AOI = mapping(box(36.0, -1.2, 36.2, -1.0))


def _reference(tmp_path, status="PENDING OWNER APPROVAL"):
    features = [{"type": "Feature", "properties": {"shapeID": sid, "shapeName": name}, "geometry": mapping(geom)}
                for sid, name, geom in (("D1", "West  District", box(35.9, -1.3, 36.1, -0.9)),
                                        ("D2", "East", box(36.1, -1.3, 36.3, -0.9)),
                                        ("D3", "Far", box(40, -5, 41, -4)))]
    data = json.dumps({"type": "FeatureCollection", "features": features}).encode()
    folder = tmp_path / "boundaries" / "tza"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "d.geojson").write_bytes(data)
    entry = {"boundaryID": "B2", "release_type": "gbOpen", "year_represented": "2021", "source": "NBS", "licence": "CC BY 3.0 IGO",
             "url": "u", "file": "d.geojson", "sha256": hashlib.sha256(data).hexdigest()}
    return {"release": "r", "citation": "c", "files": {"districts": entry, "region_lookup": {**entry, "boundaryID": "B1"}},
            "district_region_table": {"file": "t.csv", "method": "m", "status": status}}


_MANIFEST, _FEATURES = bs.manifest, bs._features  # the cached originals


@pytest.fixture
def patched(tmp_path, monkeypatch):
    def use(status="PENDING OWNER APPROVAL"):
        man = _reference(tmp_path, status)
        _MANIFEST.cache_clear(); _FEATURES.cache_clear()
        monkeypatch.setattr(bs, "manifest", lambda country="tza": man)
        monkeypatch.setattr(bs, "district_region_table", lambda country="tza": {"D1": "Pwani", "D2": "Pwani", "D3": "Lindi"})
        return bs.GeoBoundariesDistricts(tmp_path)
    return use


def test_districts_intersecting_the_aoi_with_clean_names_and_provenance(patched):
    result = patched().units(AOI)
    assert [u.id for u in result.units] == ["D1", "D2"] and result.units[0].name == "West District"
    assert result.provenance["boundaryID"] == "B2" and result.provenance["licence"] == "CC BY 3.0 IGO"
    assert result.units[0].parent is None  # the region table is not used before approval


def test_a_changed_file_is_never_used(patched, tmp_path):
    districts = patched()
    (tmp_path / "boundaries" / "tza" / "d.geojson").write_text("{}")
    _FEATURES.cache_clear()
    result = districts.units(AOI)
    assert isinstance(result, bs.NotProvided) and result.reason == bs.FILE_UNAVAILABLE


def test_regions_wait_for_approval_then_are_grouped_from_districts(patched):
    pending = bs.GroupedRegions(patched()).units(AOI)
    assert isinstance(pending, bs.NotProvided) and "waiting for the owner's approval" in pending.reason
    approved = bs.GroupedRegions(patched("APPROVED by the owner 2026-11-20")).units(AOI)
    assert [u.name for u in approved.units] == ["Pwani"]
    assert approved.units[0].geometry.equals(box(35.9, -1.3, 36.3, -0.9))  # union of its districts: exact nesting
    assert approved.provenance["grouping"]["region_lookup"]["boundaryID"] == "B1"


def test_wards_only_from_an_approved_client_dataset(monkeypatch):
    import app.services.source_data.boundaries as boundaries
    monkeypatch.setattr(boundaries, "approved_boundary_sources", lambda db, project_id: iter(()))
    result = bs.ReviewedWards(None, "p").units(AOI)
    assert isinstance(result, bs.NotProvided) and result.reason == "Ward boundaries not yet provided"
    ward = {"type": "Feature", "geometry": mapping(box(36.0, -1.1, 36.1, -1.0)),
            "properties": {"spatial_unit_id": "TZ-W1", "name": "Ikwiriri", "level": "ward"}}
    source = SimpleNamespace(data=json.dumps({"features": [ward]}), dataset=SimpleNamespace(id="ds"), evidence={"reviewed_at": "t"},
                             manifest=SimpleNamespace(category="administrative_boundaries", source_id="nbs", sha256="AB",
                                                      licence=SimpleNamespace(model_dump=lambda: {"name": "client"})))
    monkeypatch.setattr(boundaries, "approved_boundary_sources", lambda db, project_id: iter([source]))
    result = bs.ReviewedWards(None, "p").units(AOI)
    assert [u.name for u in result.units] == ["Ikwiriri"] and result.provenance["dataset_id"] == "ds"


REAL = Path(os.environ.get("REFERENCE_DATA_DIR", Path.home() / "frris-guide-data" / "reference"))


@pytest.mark.skipif(not (REAL / "boundaries" / "tza" / "geoBoundaries-TZA-ADM2.geojson").exists(), reason="pinned file not fetched")
def test_rufiji_aoi_falls_in_rufiji_district_of_pwani():
    _MANIFEST.cache_clear(); _FEATURES.cache_clear()
    rufiji = mapping(box(38.92, -7.99, 39.01, -7.90))
    names = [u.name for u in bs.GeoBoundariesDistricts(REAL).units(rufiji).units]
    assert names == ["Rufiji"]
    assert bs.district_region_table()[next(u.id for u in bs.GeoBoundariesDistricts(REAL).all_units() if u.name == "Rufiji")] == "Pwani"


def test_real_manifest_approval_name_fixes_and_limitation():
    _MANIFEST.cache_clear()
    assert bs.regions_approved()
    assert bs.clean_name("Babati UrbanBabati Urban") == "Babati Urban" and bs.clean_name("Butiam") == "Butiama"
    assert bs.clean_name("Kigoma  Urban") == "Kigoma Urban"
    assert any("Kibiti" in text and "Buchosa" in text and "NBS 2022 council list" in text for text in bs.limitations())


@pytest.mark.skipif(not (REAL / "boundaries" / "tza" / "geoBoundaries-TZA-ADM2.geojson").exists(), reason="pinned file not fetched")
def test_real_regions_are_31_including_songwe_and_keep_source_names():
    _MANIFEST.cache_clear(); _FEATURES.cache_clear()
    districts = bs.GeoBoundariesDistricts(REAL).all_units()
    assert {u.parent for u in districts} >= {"Songwe", "Pwani"} and len({u.parent for u in districts}) == 31
    babati = next(u for u in districts if u.source_name == "Babati UrbanBabati Urban")
    assert babati.name == "Babati Urban" and babati.parent == "Manyara"
    songwe = bs.GroupedRegions(bs.GeoBoundariesDistricts(REAL)).units(mapping(box(32.5, -9.5, 33.5, -8.8)))
    assert "Songwe" in [u.name for u in songwe.units]


def test_resolve_never_raises_missing_files_and_a_failing_database_are_stated(tmp_path, monkeypatch):
    import app.db.session as session
    def broken():
        raise RuntimeError("database down")
    monkeypatch.setattr(session, "SessionLocal", broken)
    _MANIFEST.cache_clear(); _FEATURES.cache_clear()
    out = bs.resolve_admin_boundaries(AOI, "p", reference_dir=tmp_path)
    assert {k: (type(v).__name__, v.reason) for k, v in out.items()} == {
        "L1": ("NotProvided", bs.FILE_UNAVAILABLE), "L2": ("NotProvided", bs.FILE_UNAVAILABLE),
        "L3": ("NotProvided", "Ward boundaries could not be read for this run.")}
