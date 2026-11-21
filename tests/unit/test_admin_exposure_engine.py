"""FRRIS v1.1 exposure by administrative unit through the engine (Exposure fakes; boundaries patched)."""
import json

from shapely.geometry import box

from shapely.geometry import Point

from app.services.firris import admin_units as au
from app.services.firris import boundary_sources as bs
from app.services.gee import open_buildings as ob
from tests.unit.test_exposure_engine import _run

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
