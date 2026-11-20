"""FRRIS v1.1 exposure by administrative unit: pieces, shares and the sums invariant (synthetic, no Earth Engine)."""
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.transform import Affine
from shapely.geometry import Point, box, mapping

from app.services.firris import admin_units as au
from app.services.firris.exposure import extent_fraction

AOI = mapping(box(36.0, -1.2, 36.2, -1.0))
POP_T = Affine(0.01, 0, 36.0, 0, -0.01, -1.0)          # 0.01° cells over the AOI (20 × 20)
POP = SimpleNamespace(population=np.arange(400, dtype=np.float64).reshape(20, 20) % 7 + 1.0, transform=POP_T)
OBS = np.zeros((40, 40), bool); OBS[5:30, 10:35] = True  # an observed extent on a 0.005° grid
OBS_T = Affine(0.005, 0, 36.0, 0, -0.005, -1.0)
BUILDINGS = [Point(36.0 + (i % 37) * 0.0053 + 0.001, -1.0 - (i // 37) * 0.0051 - 0.001) for i in range(37 * 39)]

# West unit extends past the AOI and overlaps the east unit by 0.02°; a 0.02° gap is left at the south.
WEST = au.Unit("W", "West", "L2", box(35.9, -1.18, 36.12, -0.9), code="W1", parent="R")
EAST = au.Unit("E", "East", "L2", box(36.10, -1.18, 36.3, -0.9), code="E1", parent="R")


def count(geometry):
    n = sum(1 for p in BUILDINGS if geometry.covers(p))
    return {"0.75": {"count": n}, "0.65": {"count": n + 1 if n else 0}}


def _totals():
    totals = {}
    for key, mask, mask_t, geometry in (("whole_area", None, None, box(36.0, -1.2, 36.2, -1.0)),
                                        ("observed_extent", OBS, OBS_T, None)):
        fraction = extent_fraction(POP_T, POP.population.shape, AOI, include=[] if mask is None else [(mask, mask_t)])
        totals[key] = {"people": float((POP.population * fraction).sum())}
    return totals


def _extent_geometries():
    from app.services.firris.exposure import extent_geometry
    return {"whole_area": box(36.0, -1.2, 36.2, -1.0), "observed_extent": extent_geometry(OBS, OBS_T, AOI)}


def test_pieces_are_disjoint_cover_the_aoi_and_follow_the_overlap_rule():
    pieces = au.disjoint_pieces([EAST, WEST], AOI)
    real = [p for p in pieces if p.unit]
    assert real[0].unit.id == "W"  # larger area inside the AOI takes the overlap
    assert real[0].geometry.intersection(real[1].geometry).area == pytest.approx(0, abs=1e-12)
    total = sum(p.geometry.area for p in pieces)
    assert total == pytest.approx(box(36.0, -1.2, 36.2, -1.0).area)
    outside = pieces[-1]
    assert outside.unit is None and outside.geometry.area == pytest.approx(0.2 * 0.02)  # the southern gap


def test_share_of_unit_inside_the_aoi():
    west = next(p for p in au.disjoint_pieces([WEST, EAST], AOI) if p.unit and p.unit.id == "W")
    full, inside = au.area_km2(WEST.geometry), au.area_km2(box(36.0, -1.18, 36.12, -1.0))
    assert west.share_of_unit_in_aoi == pytest.approx(inside / full, rel=1e-6)
    assert 0 < west.share_of_unit_in_aoi < 1


def test_units_add_up_to_the_area_totals_people_within_tolerance_buildings_exactly():
    totals = _totals()
    for key, geometry in _extent_geometries().items():
        totals[key]["buildings"] = count(geometry)["0.75"]["count"]
    record = au.level_breakdown(au.BoundaryUnits("L2", [WEST, EAST], {"dataset": "test"}), population=POP, aoi_geometry=AOI,
                                extents=[("whole_area", "Whole area", None, None), ("observed_extent", "Observed", OBS, OBS_T)],
                                totals=totals, count=count, extent_geometries=_extent_geometries())
    assert record["status"] == "assessed" and record["check"]["ok"]
    for key in ("whole_area", "observed_extent"):
        entry = record["check"]["extents"][key]
        assert abs(entry["people_units"] - entry["people_total"]) < 1e-6
        assert entry["buildings_units"] == entry["buildings_total"]
    names = [row["name"] for row in record["rows"]]
    assert names == ["West", "East", "Outside any unit"]  # the gap holds people, so the outside row is shown


def test_a_breach_withholds_the_level_instead_of_rescaling():
    totals = _totals()
    totals["whole_area"]["people"] += 10  # pretend the AOI total differs
    record = au.level_breakdown(au.BoundaryUnits("L2", [WEST, EAST], {}), population=POP, aoi_geometry=AOI,
                                extents=[("whole_area", "Whole area", None, None)], totals={"whole_area": totals["whole_area"]},
                                count=None, extent_geometries={})
    assert record["status"] == "not_available" and "withheld rather than rescaled" in record["reason"]


def test_people_tolerance_is_half_a_person_or_a_hundredth_of_a_percent():
    assert au.people_tolerance(100) == 0.5
    assert au.people_tolerance(57_361) == pytest.approx(5.7361)


def test_wards_not_provided_is_stated_and_nothing_else_is_filled_in():
    record = au.level_breakdown(au.NotProvided("L3", au.WARDS_NOT_PROVIDED), population=POP, aoi_geometry=AOI,
                                extents=[], totals={}, count=None, extent_geometries={})
    assert record == {"level": "L3", "level_name": "Ward", "status": "not_provided",
                      "reason": "Ward boundaries not yet provided", "provenance": {}}
