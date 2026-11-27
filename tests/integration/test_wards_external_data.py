"""Client ward layer through the External data review (owner request 2026-11-27), with enforcement ON and OFF.

Upload (an admin) -> validate -> approval by a different admin/owner -> the FRRIS ward source reads it (verified
bytes, per-version index, touching wards only, provenance line); changed bytes are refused; the route takes a file of
the NBS size (26 MB) and refuses one above 50 MiB.
"""
import hashlib
import json
import math

import pytest
from shapely.geometry import box, mapping

from app.core.config import get_settings
from app.services.firris import boundary_sources as bs
from tests.integration.test_management_bundle import setup_org

STATEMENT = ("Ward boundaries supplied by the client on 22 Nov 2026, described by the client as NBS boundaries. Year: not "
             "officially confirmed; evidence points to 2022. Licence: unconfirmed; the MIT notice belongs to the GitHub "
             "repository. Client statement of 23 Nov 2026: the data are public, and the client agreed to proceed.")
CHECKS = {"evidence_refs": ["client statement 2026-11-23; validation 2026-11-22"],
          **{k: True for k in ("qa_verified", "licence_verified", "provenance_verified", "crs_datum_verified",
                               "temporal_coverage_verified", "uncertainty_reviewed")}}


def _ward(code, name, geom, council="Rufiji DC"):
    return {"type": "Feature", "geometry": geom if isinstance(geom, dict) else mapping(geom), "properties": {
        "spatial_unit_id": code, "name": name, "level": "ward", "observed_at": "2026-11-22T00:00:00Z", "quality_flag": "valid",
        "provenance_status": "unconfirmed", "ward_code": code[-3:], "delivered_code": code, "council_code": code[:6],
        "council_name": "Halmashauri ya Wilaya ya Rufiji", "council_name_display": "Halmashauri ya Wilaya ya Rufiji",
        "council_short": council, "district_code": code[:4], "district_name": "Rufiji", "region_code": code[:2], "region_name": "Pwani"}}


def _metadata(bounds):
    west, south, east, north = bounds
    return {"source_id": "client-nbs-wards-2026-11-22", "crs": "EPSG:4326", "vertical_datum": None, "units": "boundary_polygon",
            "temporal_coverage": {"start": "2026-11-22T00:00:00Z", "end": "2026-11-22T00:00:00Z"},
            "geographic_coverage": {"west": west, "south": south, "east": east, "north": north},
            "spatial_resolution": None, "positional_uncertainty_m": 0.11, "spatial_unit_reference": "ward (Kata)",
            "quality_assessment": {"method": "Geometry validity, overlaps, gaps, nesting, duplicate codes", "assessed_at": "2026-11-22T12:00:00Z",
                                   "assessor": "NOVAREX operator", "status": "passed"},
            "uncertainty": {"measure": "Coordinate rounding only; the source states no positional accuracy", "value": 0.11, "unit": "m"},
            "licence": {"identifier": "unconfirmed (MIT notice belongs to the GitHub repository)",
                        "permitted_use": "Client instruction of 23 Nov 2026: proceed with the data at hand", "redistribution": "restricted"},
            "provenance": {"producer": "Described by the client as NBS (not officially confirmed)", "custodian": "Client (supplied 22 Nov 2026)",
                           "source_uri": "github.com/Heed725/Tanzania_Admin_Shapefiles (identical files)",
                           "acquisition_method": "Delivered by the client; converted with scripts/convert_nbs_wards.py"},
            "management": {"provenance_statement": STATEMENT, "year": "not officially confirmed; evidence points to 2022",
                           "licence": "unconfirmed; MIT notice belongs to the GitHub repository"}}


@pytest.fixture(autouse=True)
def _fresh_index():
    bs._ward_index.cache_clear()
    yield
    bs._ward_index.cache_clear()


@pytest.mark.parametrize("enforcement", [True, False], ids=["enforcement-on", "enforcement-off"])
def test_ward_layer_upload_second_admin_approval_and_use(enforcement, client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "billing_enforcement_enabled", enforcement)
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    org, people, project, headers = setup_org(db_session)
    wards = [_ward("060511013", "Ikwiriri", box(36.0, -1.1, 36.1, -1.0)), _ward("060511023", "Mgomba", box(36.1, -1.1, 36.2, -1.0)),
             _ward("060711131", "Mtunda", box(40.0, -5.0, 40.1, -4.9), council="Kibiti DC")]
    data = json.dumps({"type": "FeatureCollection", "features": wards}).encode()
    base = f"/api/v1/projects/{project.id}/external-datasets"
    upload = client.post(base, headers=headers("admin"), files={"file": ("nbs-wards-2026-11-22.geojson", data, "application/geo+json")},
                         data={"manifest": json.dumps({"title": "NBS-derived wards (client, 22 Nov 2026)", "category": "administrative_boundaries",
                                                       "metadata": _metadata((36.0, -5.0, 40.1, -1.0))})})
    assert upload.status_code == 201, upload.text
    key = upload.json()["id"]
    validated = client.post(f"{base}/{key}/validate", headers=headers("admin"))
    assert validated.status_code == 200 and validated.json()["status"] == "Needs Scientific Review", validated.text
    assert bs.ReviewedWards(db_session, project.id).units(mapping(box(36.0, -1.2, 36.2, -1.0))).reason == "Ward boundaries not yet provided"
    body = {"decision": "approve", "reason": "Client ward layer; provenance unconfirmed and recorded", "review": CHECKS}
    assert client.post(f"{base}/{key}/review", headers=headers("admin"), json=body).status_code == 403  # the uploader may not approve
    assert client.post(f"{base}/{key}/review", headers=headers("analyst"), json=body).status_code == 403
    approved = client.post(f"{base}/{key}/review", headers=headers("owner"), json=body)
    assert approved.status_code == 200 and approved.json()["status"] == "Approved for Analysis", approved.text
    db_session.expire_all()
    result = bs.ReviewedWards(db_session, project.id).units(mapping(box(36.0, -1.2, 36.2, -1.0)))
    assert [u.name for u in result.units] == ["Ikwiriri", "Mgomba"] and {u.parent for u in result.units} == {"Rufiji DC"}
    assert result.provenance["provenance_statement"] == STATEMENT and result.provenance["sha256"] == hashlib.sha256(data).hexdigest()
    assert result.provenance["licence"]["identifier"].startswith("unconfirmed")
    # Another project of the same organisation never sees this layer.
    other = setup_org(db_session)[2]
    assert isinstance(bs.ReviewedWards(db_session, other.id).units(mapping(box(36.0, -1.2, 36.2, -1.0))), bs.NotProvided)
    # Changed bytes on disk are refused at run time (streamed SHA-256), even with an index already cached.
    stored = next(tmp_path.rglob("*.geojson"))
    stored.write_bytes(data.replace(b"Ikwiriri", b"Ikwiriri2"))
    tampered = bs.ReviewedWards(db_session, project.id).units(mapping(box(36.0, -1.2, 36.2, -1.0)))
    assert isinstance(tampered, bs.NotProvided)


def _nbs_size_geojson():
    features = []
    for i in range(4344):
        cx, cy = 30 + (i % 66) * 0.15, -11 + (i // 66) * 0.15
        ring = [[round(cx + 0.07 * math.cos(2 * math.pi * k / 240), 6), round(cy + 0.07 * math.sin(2 * math.pi * k / 240), 6)] for k in range(240)]
        ring.append(ring[0])
        features.append(_ward(f"{i:09d}", f"Ward {i}", {"type": "Polygon", "coordinates": [ring]}))
    return json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")).encode()


def test_the_upload_route_takes_the_nbs_size_and_refuses_above_50_mib(client, db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "output_storage_dir", str(tmp_path))
    org, people, project, headers = setup_org(db_session)
    base = f"/api/v1/projects/{project.id}/external-datasets"
    big = _nbs_size_geojson()
    assert 20 * 1024 * 1024 < len(big) < 50 * 1024 * 1024
    manifest = json.dumps({"title": "NBS-size wards", "category": "administrative_boundaries", "metadata": {}})
    ok = client.post(base, headers=headers("admin"), data={"manifest": manifest}, files={"file": ("wards.geojson", big, "application/geo+json")})
    assert ok.status_code == 201, ok.text[:300]
    too_big = big + b" " * (50 * 1024 * 1024 + 1 - len(big))
    refused = client.post(base, headers=headers("admin"), data={"manifest": manifest}, files={"file": ("wards.geojson", too_big, "application/geo+json")})
    assert refused.status_code == 413 and "50 MiB" in refused.text
