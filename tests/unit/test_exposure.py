"""Depth & Exposure module, Phase 2: population year labels, area weighting, building counts with tiling, rows."""
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.transform import Affine
from shapely.geometry import Point, box

from app.services.firris import exposure as ex
from app.services.gee import open_buildings as ob
from app.services.gee import worldpop as wp

C = 1 / 1200  # 3 arc-seconds


def _box(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


# --- 2.1 WorldPop year labels ------------------------------------------------------------------------------------

@pytest.mark.parametrize("year, status, words", [
    (2015, "interpolated", "interpolated between the 2012 and 2022 censuses"),
    (2021, "interpolated", "interpolated between the 2012 and 2022 censuses"),
    (2022, "census-anchored", "anchored on the 2022 census"),
    (2023, "projected", "a projection 1 year after the last census (2022)"),
    (2024, "projected", "a projection 2 years after the last census (2022)"),
    (2030, "projected", "a projection 8 years after the last census (2022)"),
])
def test_tanzania_years_are_labelled_from_the_census_inputs(year, status, words):
    label = wp.year_status(["TZA"], year)
    assert label["status"] == status and words in label["text"] and label["census_input_years"] == [2012, 2022]
    assert "UN World Population Prospects 2024" in label["text"]


def test_other_countries_are_modelled_without_invented_census_years():
    label = wp.year_status(["KEN"], 2024)
    assert label["status"] == "modelled" and label["census_input_years"] is None and "not recorded" in label["text"]
    assert wp.year_status(["TZA", "KEN"], 2024)["status"] == "modelled"


def test_population_year_is_clamped_to_the_series():
    assert (wp.population_year(2010), wp.population_year(2024), wp.population_year(2035)) == (2015, 2024, 2030)


# --- area weighting ----------------------------------------------------------------------------------------------

def test_sample_mask_is_false_outside_the_raster():
    mask = np.ones((2, 2), bool)
    t = Affine(1, 0, 0, 0, -1, 2)
    assert list(ex.sample_mask(mask, t, np.array([0.5, 1.5, 5.0]), np.array([1.5, 0.5, 1.0]))) == [True, True, False]


def test_extent_fraction_area_weights_a_finer_mask_and_the_aoi():
    t = Affine(C, 0, 39.0, 0, -C, -8.0)
    aoi = _box(39.0, -8.0 - 2 * C, 39.0 + 2 * C, -8.0)
    fine = np.zeros((4, 4), bool)
    fine[0, 0] = True  # a quarter of cell (0, 0)
    fine[2:, 2:] = True  # all of cell (1, 1)
    fraction = ex.extent_fraction(t, (2, 2), aoi, include=[(fine, Affine(C / 2, 0, 39.0, 0, -C / 2, -8.0))], subcells=10)
    assert fraction == pytest.approx(np.array([[0.25, 0], [0, 1]]))
    half_aoi = _box(39.0, -8.0 - 2 * C, 39.0 + C, -8.0)
    assert ex.extent_fraction(t, (2, 2), half_aoi, subcells=10) == pytest.approx(np.array([[1, 0], [1, 0]]))


def test_extent_geometry_is_clipped_to_the_aoi():
    mask = np.ones((4, 4), bool)
    t = Affine(1, 0, 0, 0, -1, 4)
    geometry = ex.extent_geometry(mask, t, _box(0, 0, 2, 4))
    assert geometry.area == pytest.approx(8)
    assert ex.extent_geometry(np.zeros((2, 2), bool), t, _box(0, 0, 2, 4)).is_empty


# --- 2.2 building counts: exact, tiling only on time-out, no sampling -------------------------------------------

POINTS = [(x + 0.5, y + 0.5) for x in range(8) for y in range(8)] + [(4.0, 4.0), (2.0, 6.0), (6.0, 2.0)]  # some on split lines


def _fake_call(slow_above=None, sleep=0.5, calls=None):
    def call(geometry, bounds):
        if calls is not None:
            calls.append(bounds)
        w, s, e, n = bounds
        if slow_above is not None and (e - w) > slow_above:
            time.sleep(sleep)
        inside = [p for p in POINTS if w <= p[0] < e and s <= p[1] < n and geometry.covers(Point(p))]
        return {"0.75": {"count": len(inside), "area_m2": 10.0 * len(inside)}, "0.65": {"count": 2 * len(inside), "area_m2": 0.0}}
    return call


def test_one_call_when_fast():
    calls = []
    result = ob.count_buildings(box(0, 0, 8, 8), call=_fake_call(calls=calls))
    assert result["0.75"]["count"] == len(POINTS) and result["tiles"] == 1 and len(calls) == 1
    assert result["method"] == "centroid inside the extent; exact server-side count"


def test_tiles_after_a_timeout_count_every_building_exactly_once():
    calls = []
    result = ob.count_buildings(box(0, 0, 8, 8), call=_fake_call(slow_above=4.5, calls=calls), call_budget_s=0.1)
    assert result["0.75"]["count"] == len(POINTS)  # points on the split lines are not double-counted
    assert result["0.65"]["count"] == 2 * len(POINTS)
    assert result["tiles"] == 4 and result["depth"] == 1 and "4 tiles" in result["method"]


def _times_out_above(width):
    """Deterministic: Earth Engine's own time-out error for tiles wider than ``width`` (no wall-clock timing)."""
    def call(geometry, bounds):
        if bounds[2] - bounds[0] > width:
            raise RuntimeError("Computation timed out.")
        return _fake_call()(geometry, bounds)
    return call


def test_recursive_tiling_and_the_depth_limit():
    result = ob.count_buildings(box(0, 0, 8, 8), call=_times_out_above(2.5))
    assert result["0.75"]["count"] == len(POINTS) and result["depth"] == 2 and result["tiles"] == 16
    with pytest.raises(ob.BuildingCountUnavailable, match="timed out even after splitting"):
        ob.count_buildings(box(0, 0, 8, 8), call=_times_out_above(0.0), max_depth=1)


def test_earth_engine_timeout_errors_also_split():
    seen = []

    def call(geometry, bounds):
        seen.append(bounds)
        if bounds[2] - bounds[0] > 4.5:
            raise RuntimeError("Computation timed out.")
        return _fake_call()(geometry, bounds)
    assert ob.count_buildings(box(0, 0, 8, 8), call=call)["0.75"]["count"] == len(POINTS) and len(seen) == 5


def test_total_budget_and_other_errors_are_not_available():
    with pytest.raises(ob.BuildingCountUnavailable, match="did not finish within"):
        ob.count_buildings(box(0, 0, 8, 8), call=_fake_call(slow_above=0.0, sleep=0.2), call_budget_s=0.05, total_budget_s=0.0)

    def broken(geometry, bounds):
        raise RuntimeError("quota exceeded")
    with pytest.raises(ob.BuildingCountUnavailable, match="quota exceeded"):
        ob.count_buildings(box(0, 0, 8, 8), call=broken)


def test_empty_extent_counts_zero_without_a_call():
    from shapely.geometry import GeometryCollection
    assert ob.count_buildings(GeometryCollection(), call=None)["0.75"] == {"count": 0, "area_m2": 0.0}


# --- 2.3 rows ----------------------------------------------------------------------------------------------------

def _population(values):
    return wp.PopulationGrid(population=np.asarray(values, np.float32), transform=Affine(C, 0, 39.0, 0, -C, -8.0), year=2024,
                             requested_year=2024, countries=["TZA"], images=["TZA_2024"])


def _hazard():
    depth = np.full((4, 4), np.nan, np.float32)
    depth[:2, :] = 1.0  # north half wet
    permanent = np.zeros((4, 4), bool)
    permanent[0, :] = True  # the first row is permanent water
    return {"transform": Affine(C, 0, 39.0, 0, -C, -8.0), "inside": np.ones((4, 4), bool), "permanent_water": permanent,
            "spurious": np.zeros((4, 4), bool), "depth": {p: depth for p in (10, 20, 50, 75, 100, 200, 500)}}


def _count(geometry):
    return {"0.75": {"count": int(round(geometry.area / C / C)), "area_m2": 1.0}, "0.65": {"count": 0, "area_m2": 0.0},
            "tiles": 1, "depth": 0, "seconds": 0.0, "method": "fake"}


def test_rows_area_weight_people_and_exclude_permanent_water_like_the_hazard():
    aoi = _box(39.0, -8.0 - 4 * C, 39.0 + 4 * C, -8.0)
    population = _population(np.full((4, 4), 10.0))
    observed = {"extent": np.ones((4, 4), bool), "transform": Affine(C, 0, 39.0, 0, -C, -8.0)}
    rows, arrays = ex.exposure_rows(population, aoi, observed=observed, hazard_layers=_hazard(), count=_count)
    by = {r["extent"]: r for r in rows}
    assert list(by) == ["whole_area", "observed_extent", "rp10", "rp20", "rp50", "rp75", "rp100", "rp200", "rp500"]
    assert by["whole_area"]["people"] == pytest.approx(160)
    assert by["observed_extent"]["people"] == pytest.approx(120)  # 4 of 16 cells are permanent water
    assert by["observed_extent"]["including_permanent_water"]["people"] == pytest.approx(160)
    assert by["rp100"]["people"] == pytest.approx(40) and by["rp100"]["including_permanent_water"]["people"] == pytest.approx(80)
    assert by["rp100"]["buildings"]["0.75"]["count"] == 4 and by["rp100"]["buildings"]["status"] == "counted"
    assert all(r["people_cells_touching"] >= r["people"] - 1e-6 for r in rows)
    assert set(arrays) == {"observed_extent", "rp100"} and arrays["rp100"]["people"].sum() == pytest.approx(40)


def test_building_count_unavailable_keeps_the_population_row():
    def unavailable(geometry):
        raise ob.BuildingCountUnavailable("too dense")
    aoi = _box(39.0, -8.0 - 4 * C, 39.0 + 4 * C, -8.0)
    rows, _ = ex.exposure_rows(_population(np.ones((4, 4))), aoi, observed=None, hazard_layers=None, count=unavailable)
    assert rows[0]["buildings"] == {"status": "not_available", "reason": "too dense"} and rows[0]["people"] == pytest.approx(16)


def test_record_states_year_method_threshold_and_never_affected():
    record = ex.exposure_record(_population(np.ones((2, 2))), [])
    assert record["population"]["year_status"]["status"] == "projected"
    assert "area-weighted" in record["population"]["method"] and record["buildings"]["primary_threshold"] == 0.75
    assert "Not people affected" in record["wording"] and "doi:10.5258/SOTON/WP00839" in record["population"]["citation"]
    assert "arXiv:2107.12283" in record["buildings"]["citation"]


def test_run_exposure_reports_unavailable_states():
    aoi = _box(39.0, -8.0 - 4 * C, 39.0 + 4 * C, -8.0)
    def missing(aoi, year):
        raise wp.PopulationUnavailable("no grid")
    def broken(aoi, year):
        raise RuntimeError("down")
    assert ex.run_exposure(aoi, event_year=2024, extent=None, extent_transform=None, extent_crs="EPSG:4326", hazard_layers=None,
                           acquire=missing)[0] == ex.unavailable_exposure("no grid")
    assert "could not be read" in ex.run_exposure(aoi, event_year=2024, extent=None, extent_transform=None, extent_crs="EPSG:4326",
                                                  hazard_layers=None, acquire=broken)[0]["reason"]
    assert "EPSG:4326" in ex.run_exposure(aoi, event_year=2024, extent=None, extent_transform=None, extent_crs="EPSG:32737",
                                          hazard_layers=None)[0]["reason"]
    assert "target period" in ex.run_exposure(aoi, event_year=None, extent=None, extent_transform=None, extent_crs="EPSG:4326",
                                              hazard_layers=None)[0]["reason"]
