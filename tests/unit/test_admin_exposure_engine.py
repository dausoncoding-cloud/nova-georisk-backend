"""FRRIS v1.1 exposure by administrative unit through the engine (Exposure fakes; boundaries patched)."""
import json
import sqlite3
import zipfile

import pyogrio
import pytest
from openpyxl import load_workbook
from shapely.geometry import box

from shapely.geometry import Point

from app.services.firris import admin_units as au
from app.services.firris import boundary_sources as bs
from app.services.gee import open_buildings as ob
from tests.unit.test_exposure_engine import _run, _text

# An additive building count, like the real one (centroid inside; disjoint pieces): fixed points, none on a unit border.
POINTS = [Point(36.0 + 0.00731 * i + 0.0013, -1.0 - 0.00617 * j - 0.0011) for i in range(82) for j in range(97)]


def _point_count(geometry, **kwargs):
    from shapely.prepared import prep
    inside = prep(geometry)
    n = sum(1 for p in POINTS if inside.contains(p))
    return {"0.75": {"count": n, "area_m2": n * 50.0}, "0.65": {"count": n + n // 4, "area_m2": n * 60.0},
            "tiles": 1, "depth": 0, "seconds": 0.0, "method": "fake points"}


def _boundaries(aoi, project_id, **kwargs):
    district = au.Unit("D1", "Rufiji", "L2", box(35.9, -1.7, 36.3, -0.9), parent="Pwani")
    other = au.Unit("D2", "Kibiti-like", "L2", box(36.3, -1.7, 36.7, -0.9), parent="Pwani")
    region = au.Unit("region:Pwani", "Pwani", "L1", box(35.5, -2.0, 37.0, -0.5))
    return {"L1": au.BoundaryUnits("L1", [region], {"dataset": "geoBoundaries", "licence": "CC BY 3.0 IGO"}),
            "L2": au.BoundaryUnits("L2", [district, other], {"dataset": "geoBoundaries", "licence": "CC BY 3.0 IGO"}),
            "L3": au.NotProvided("L3", au.WARDS_NOT_PROVIDED)}


def test_engine_summary_carries_the_breakdown_and_it_adds_up(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(bs, "resolve_admin_boundaries", lambda aoi, pid, **k: seen.append(pid) or _boundaries(aoi, pid))
    output = _run(tmp_path, _WithCount(monkeypatch))
    exposure = output.summary["flood_exposure"]
    by = exposure["by_admin_unit"]
    assert seen and by["status"] == "assessed"
    levels = {lv["level"]: lv for lv in by["levels"]}
    assert levels["L3"]["status"] == "not_provided" and levels["L3"]["reason"] == "Ward boundaries not yet provided"
    for key in ("L1", "L2"):
        assert levels[key]["status"] == "assessed" and levels[key]["check"]["ok"], levels[key]["check"]
    rows = {r["extent"]: r for r in exposure["rows"]}
    l2 = levels["L2"]["check"]["extents"]
    assert l2["observed_extent"]["buildings_units"] == rows["observed_extent"]["buildings"]["0.75"]["count"]
    assert abs(l2["whole_area"]["people_units"] - rows["whole_area"]["people"]) <= au.people_tolerance(rows["whole_area"]["people"])
    json.dumps(by)  # stored with the result


class _WithCount:
    """Passes through to monkeypatch, but keeps the additive count when _run installs its own fake."""
    def __init__(self, mp):
        self.mp = mp
    def setattr(self, target, name, value, *args):
        if target is ob and name == "count_buildings":
            value = _point_count
        return self.mp.setattr(target, name, value, *args)


def test_a_count_that_does_not_add_up_withholds_the_level_instead_of_rescaling(tmp_path, monkeypatch):
    monkeypatch.setattr(bs, "resolve_admin_boundaries", lambda aoi, pid, **k: _boundaries(aoi, pid))
    output = _run(tmp_path, monkeypatch)  # the engine fake: int(km2), which is not additive
    levels = {lv["level"]: lv for lv in output.summary["flood_exposure"]["by_admin_unit"]["levels"]}
    assert levels["L2"]["status"] == "not_available" and "withheld rather than rescaled" in levels["L2"]["reason"]
    assert levels["L1"]["status"] == "assessed"  # one region holds the whole AOI: the totals themselves
    assert output.summary["flood_exposure"]["status"] == "assessed"


def test_without_exposure_no_boundaries_are_resolved(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(bs, "resolve_admin_boundaries", lambda *a, **k: seen.append(1) or {})
    output = _run(tmp_path, monkeypatch, exposure=False)
    assert not seen and "by_admin_unit" not in (output.summary.get("flood_exposure") or {})


def _many_districts(aoi, project_id, **kwargs):
    """20 district strips across the engine AOI (36.0-36.6 E), so the report needs "Other units"."""
    units = [au.Unit(f"D{i:02d}", f"District {i:02d}", "L2", box(36.0 + 0.03 * i, -1.7, 36.0 + 0.03 * (i + 1), -0.9), parent="Pwani")
             for i in range(20)]
    region = au.Unit("region:Pwani", "Pwani", "L1", box(35.5, -2.0, 37.0, -0.5))
    prov = {"dataset": "geoBoundaries", "release": "geoBoundaries commit 9469f09", "boundaryID": "TZA-ADM2-72390352",
            "release_type": "gbOpen", "year_represented": "2021", "source": "NBS / UN OCHA ROSA", "licence": "CC BY 3.0 IGO",
            "citation": "Runfola, D. et al. (2020).", "limitations": ["The 170-district layer predates newer councils (for example Kibiti)."]}
    return {"L1": au.BoundaryUnits("L1", [region], prov), "L2": au.BoundaryUnits("L2", units, prov),
            "L3": au.NotProvided("L3", au.WARDS_NOT_PROVIDED)}


@pytest.fixture(scope="module")
def outputs(tmp_path_factory):
    directory = tmp_path_factory.mktemp("admin-exposure")
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(bs, "resolve_admin_boundaries", _many_districts)
        result = _run(directory, _WithCount(mp))
    finally:
        mp.undo()
    return result, directory, _text(directory / result.output_files["scientific_report_pdf"]["path"])


def test_report_subsection_top_15_other_units_sum_check_wards_and_limitations(outputs):
    result, directory, text = outputs
    levels = {lv["level"]: lv for lv in result.summary["flood_exposure"]["by_admin_unit"]["levels"]}
    assert levels["L2"]["status"] == "assessed", levels["L2"]["check"]
    assert "Exposure by administrative unit" in text and "Other units (5)" in text
    assert "The top 15 of 20 units by people in the observed flood candidates" in text
    assert "Units add up to the area total for the observed flood candidates:" in text and "buildings." in text
    assert "Wards: Ward boundaries not yet provided." in text
    assert "predates newer councils" in text and "CC BY 3.0 IGO" in text and "TZA-ADM2-72390352" in text
    assert "District 00 (Pwani)" in text or "District 19 (Pwani)" in text


def test_workbook_csv_geopackage_and_package_readme(outputs):
    result, directory, _ = outputs
    files = result.output_files
    sheets = load_workbook(directory / files["firris_excel_report"]["path"], read_only=True)
    assert "Exposure by admin unit" in sheets.sheetnames
    ws = sheets["Exposure by admin unit"]
    rows = list(ws.iter_rows(values_only=True))
    districts = {r[1] for r in rows[1:] if r[0] == "District"}
    assert len(districts) == 20 and rows[0][:3] == ("level", "unit_id", "unit")
    csv = (directory / files["flood_exposure_by_admin_unit_csv"]["path"]).read_text()
    assert "District 19" in csv and "Ward" in csv
    gpkg = directory / files["exposure_by_admin_unit_gpkg"]["path"]
    layers = {name for name, _ in pyogrio.list_layers(gpkg)}
    assert layers == {"regions", "districts", "about"}
    frame = pyogrio.read_dataframe(gpkg, layer="districts")
    assert len(frame) == 20 and {"ppl_observed_extent", "bld_rp100", "b65_whole_area", "share_pct", "licence"} <= set(frame.columns)
    assert abs(frame["ppl_whole_area"].sum() - next(r for r in result.summary["flood_exposure"]["rows"] if r["extent"] == "whole_area")["people"]) < 1
    with sqlite3.connect(gpkg) as db:
        descriptions = dict(db.execute("select table_name, description from gpkg_contents").fetchall())
    assert "CC BY 3.0 IGO" in descriptions["districts"] and "estimates, not people affected" in descriptions["districts"]
    about = pyogrio.read_dataframe(gpkg, layer="about")
    assert "Layer wards" in set(about["item"]) and any("predates newer councils" in v for v in about["value"])
    with zipfile.ZipFile(directory / files["report_package"]["path"]) as package:
        names = package.namelist()
        readme = package.read(next(n for n in names if n.endswith("README.txt"))).decode()
    assert any(n.endswith("exposure-by-admin-unit.gpkg") for n in names)
    assert "Licence note: administrative boundaries" in readme and "CC BY 3.0 IGO" in readme


def test_provenance_records_each_level(outputs):
    result, _, _ = outputs
    prov = result.provenance["flood_exposure"]["by_admin_unit"]
    by_level = {lv["level"]: lv for lv in prov["levels"]}
    assert by_level["L2"]["sums_check_ok"] is True and by_level["L2"]["boundaries"]["boundaryID"] == "TZA-ADM2-72390352"
    assert by_level["L3"]["status"] == "not_provided" and "Overlapping boundary areas" in by_level["L2"]["overlap_rule"]
