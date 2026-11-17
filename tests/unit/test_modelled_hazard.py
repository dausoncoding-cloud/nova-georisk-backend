"""Depth & Exposure module, Phase 1: GloFAS acquisition (1.1), hazard statistics (1.2) and occurrence table (1.4)."""
import sys
import types
from types import SimpleNamespace

import numpy as np
import pytest
from rasterio.transform import Affine

from app.services.firris import hazard_sources as src
from app.services.firris import modelled_hazard as mh
from app.services.gee import glofas_hazard as gh

CELL = 1 / 1200  # 3 arc-seconds


# --- 1.4 probabilities: the fixed values of the plan (§5) --------------------------------------------------------

@pytest.mark.parametrize("t, n, expected", [
    (10, 10, 65.1), (10, 30, 95.8), (10, 50, 99.5), (20, 10, 40.1), (20, 30, 78.5), (20, 50, 92.3), (20, 100, 99.4),
    (50, 10, 18.3), (50, 30, 45.5), (50, 50, 63.6), (50, 100, 86.7), (75, 10, 12.6), (75, 30, 33.1), (75, 50, 48.9),
    (75, 100, 73.9), (100, 10, 9.6), (100, 30, 26.0), (100, 50, 39.5), (100, 100, 63.4), (200, 10, 4.9), (200, 30, 14.0),
    (200, 50, 22.2), (200, 100, 39.4), (500, 10, 2.0), (500, 30, 5.8), (500, 50, 9.5), (500, 100, 18.1),
])
def test_probability_of_at_least_one_occurrence_matches_the_plan(t, n, expected):
    assert round(mh.probability_at_least_once(t, n) * 100, 1) == expected


def test_aep_is_one_over_t_and_one_year_probability_equals_aep():
    for t in src.RETURN_PERIODS:
        assert mh.aep(t) == pytest.approx(1 / t)
        assert mh.probability_at_least_once(t, 1) == pytest.approx(1 / t)
    assert mh.probability_at_least_once(10, 100) > 0.9999
    with pytest.raises(ValueError):
        mh.aep(1)
    with pytest.raises(ValueError):
        mh.probability_at_least_once(10, 0)


def test_occurrence_table_has_every_return_period_and_year():
    table = mh.occurrence_table()
    assert [row["return_period_years"] for row in table] == list(src.RETURN_PERIODS)
    assert all(list(row["probability_at_least_once"]) == [str(n) for n in src.OCCURRENCE_YEARS] for row in table)
    assert table[4]["probability_at_least_once"]["30"] == pytest.approx(0.2603, abs=1e-4)  # 100-year flood in 30 years


# --- grid helpers ------------------------------------------------------------------------------------------------

def _box(west, south, east, north):
    return {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]]}


def test_cell_fractions_are_one_inside_zero_outside_and_partial_on_the_edge():
    transform = Affine(CELL, 0, 39.0, 0, -CELL, -8.0)
    aoi = _box(39.0, -8.0 - 4 * CELL, 39.0 + 2.5 * CELL, -8.0)  # 2.5 cells wide, 4 cells tall
    fraction = mh.cell_fractions(aoi, transform, (4, 4))
    assert np.allclose(fraction[:, :2], 1) and np.allclose(fraction[:, 2], 0.5) and np.allclose(fraction[:, 3], 0)


def test_cell_areas_follow_the_ellipsoid():
    transform = Affine(CELL, 0, 39.0, 0, -CELL, 0.0)
    equator = mh.cell_areas_km2(transform, (1, 1))[0, 0]
    assert equator == pytest.approx(0.09277 * 0.09213, rel=0.001)  # 92.77 m × 92.13 m at the equator
    high = mh.cell_areas_km2(Affine(CELL, 0, 39.0, 0, -CELL, -60.0), (1, 1))[0, 0]
    assert high == pytest.approx(equator * np.cos(np.radians(60)), rel=0.02)  # ellipsoid: just over 1% from cos(lat)


def test_weighted_quantile():
    assert mh.weighted_quantile([1, 2, 3, 4], [1, 1, 1, 1], 0.5) == 2
    assert mh.weighted_quantile([1, 2, 3, 4], [0, 0, 1, 3], 0.5) == 4
    assert mh.weighted_quantile([1, 2], [0, 0], 0.5) is None


# --- 1.2 statistics ----------------------------------------------------------------------------------------------

def _stack(depth_rp10, *, permanent=None, spurious=None, covered=None):
    shape = depth_rp10.shape
    depth = {p: np.where(np.isfinite(depth_rp10), depth_rp10 + (i * 0.1), np.nan).astype(np.float32)
             for i, p in enumerate(src.RETURN_PERIODS)}
    return SimpleNamespace(depth=depth, transform=Affine(CELL, 0, 39.0, 0, -CELL, -8.0), crs="EPSG:4326",
                           permanent_water=np.zeros(shape, bool) if permanent is None else permanent,
                           spurious=np.zeros(shape, bool) if spurious is None else spurious,
                           covered=np.ones(shape, bool) if covered is None else covered,
                           provenance=lambda: {"asset": src.GLOFAS_ASSET})


AOI_4x4 = _box(39.0, -8.0 - 4 * CELL, 39.0 + 4 * CELL, -8.0)


def test_statistics_exclude_permanent_water_and_report_it_separately():
    depth = np.full((4, 4), np.nan)
    depth[0, :] = [0.3, 0.8, 1.5, 2.5]  # wet row
    depth[1, :2] = [4.0, 0.05]          # one deep cell, one below the 0.1 m minimum
    permanent = np.zeros((4, 4), bool)
    permanent[1, 0] = True              # the 4.0 m cell is permanent water
    record = mh.hazard_record(_stack(depth, permanent=permanent), AOI_4x4)
    rp10 = record["return_periods"][0]
    cell = record["aoi"]["area_km2"] / 16
    assert rp10["wet_cells"] == 4 and rp10["wet_area_km2"] == pytest.approx(4 * cell, rel=1e-3)
    assert rp10["wet_pct_of_aoi"] == pytest.approx(25.0, rel=1e-3)
    assert rp10["depth_m"]["max"] == pytest.approx(2.5) and rp10["depth_m"]["p50"] == pytest.approx(0.8)
    assert [c["area_km2"] / cell for c in rp10["classes"]] == pytest.approx([1, 1, 1, 1, 0], abs=1e-3)
    assert sum(c["pct_of_wet"] for c in rp10["classes"]) == pytest.approx(100)
    including = rp10["including_permanent_water"]
    assert including["wet_pct_of_aoi"] == pytest.approx(31.25, rel=1e-3) and including["depth_m"]["max"] == pytest.approx(4.0)
    assert record["permanent_water_km2"] == pytest.approx(cell, rel=1e-3)
    assert record["status"] == "assessed" and record["method"]["permanent_water"].startswith("excluded")


def test_spurious_cells_are_excluded_and_uncovered_cells_are_no_data():
    depth = np.full((4, 4), 1.0)
    spurious = np.zeros((4, 4), bool)
    spurious[0, 0] = True
    covered = np.ones((4, 4), bool)
    covered[3, :] = False
    record = mh.hazard_record(_stack(depth, spurious=spurious, covered=covered), AOI_4x4)
    assert record["return_periods"][0]["wet_cells"] == 11
    assert record["aoi"]["covered_pct"] == pytest.approx(75, rel=1e-3)
    assert record["spurious_km2"] > 0


def test_no_wet_cell_means_no_modelled_flooding_not_a_zero_result():
    record = mh.hazard_record(_stack(np.full((4, 4), np.nan)), AOI_4x4)
    assert record["status"] == "no_modelled_flooding" and "No GloFAS flood depth" in record["reason"]


def test_wet_area_grows_with_the_return_period_on_nested_extents():
    depth = np.full((4, 4), np.nan)
    depth[:2, :] = 1.0
    stack = _stack(depth)
    stack.depth[500] = np.where(np.isfinite(stack.depth[500]) | (np.arange(16).reshape(4, 4) < 12), 1.0, np.nan)
    record = mh.hazard_record(stack, AOI_4x4)
    areas = [p["wet_area_km2"] for p in record["return_periods"]]
    assert areas == sorted(areas) and areas[-1] > areas[0]


def test_observed_extent_share_is_context_and_counts_permanent_water_separately():
    depth = np.full((4, 4), np.nan)
    depth[:, :2] = 1.0  # west half wet
    permanent = np.zeros((4, 4), bool)
    permanent[0, 3] = True
    extent = np.zeros((8, 8), bool)
    extent[:, :] = True  # a 2× finer grid over the same 4×4 cells
    observed = {"extent": extent, "transform": Affine(CELL / 2, 0, 39.0, 0, -CELL / 2, -8.0), "crs": "EPSG:4326"}
    record = mh.hazard_record(_stack(depth, permanent=permanent), AOI_4x4, observed=observed)
    share = record["return_periods"][0]["observed_extent"]
    assert share["inside_pct"] == pytest.approx(50) and share["in_permanent_water_pct"] == pytest.approx(100 / 16)
    assert share["pixels"] == 64


def test_record_carries_citation_attribution_and_the_licence_from_one_place():
    record = mh.hazard_record(_stack(np.full((4, 4), 1.0)), AOI_4x4)
    assert record["citation"] == src.GLOFAS_CITATION and "jrc-floods-floodmapgl_rp50y-tif" in record["citation"]
    assert "10.1016/j.advwatres.2016.05.002" not in record["citation"]
    assert record["licence"] == src.GLOFAS_LICENCE and record["licence_confirmed"] is True and "(ODbL) v1.0" in record["licence"]
    assert "doi:10.2905/JRC.VD32YWG" in record["citation"]
    assert record["produced_work_notice"] == "Contains data from GloFAS flood hazard maps (JRC/CEMS), ODbL v1.0"
    assert "available under the Open Data Commons Open Database License (ODbL) v1.0" in record["database_notice"]
    assert "no further restrictions are added" in record["database_notice"]
    assert record["method_references"] == list(src.GLOFAS_METHOD_REFERENCES)
    assert "Flood defences are not modelled" in record["method"]["note"] and "AEP = 1/T" in record["method"]["aep"]
    unavailable = mh.unavailable_record("outside")
    assert unavailable["status"] == "not_available" and unavailable["attribution"] == src.GLOFAS_ATTRIBUTION


# --- 1.1 acquisition ---------------------------------------------------------------------------------------------

def test_native_grid_snaps_outward_to_the_dataset_grid():
    transform, width, height = gh.native_grid(30.0, 0.0, CELL, -CELL, (30.0 + 2.5 * CELL, -3.2 * CELL, 30.0 + 5.1 * CELL, -0.4 * CELL))
    assert (transform.c, transform.f) == pytest.approx((30.0 + 2 * CELL, 0.0)) and (width, height) == (4, 4)


def test_row_blocks_stay_under_the_request_limit():
    blocks = gh.row_blocks(1000, 2000, 9, limit=9 * 2000 * 4 * 300)
    assert blocks[0] == (0, 300) and blocks[-1] == (900, 1000)
    assert all(stop - start <= 300 for start, stop in blocks)


class _FakeEE(types.ModuleType):
    """The few Earth Engine calls acquire_glofas makes, answered from numpy arrays."""

    def __init__(self, features, values):
        super().__init__("ee")
        fake = self
        self.requests = []

        class Collection:
            def __init__(self, *a): pass
            def filterBounds(self, aoi): return self
            def map(self, fn): return SimpleNamespace(getInfo=lambda: {"features": features})
            def first(self): return SimpleNamespace(select=lambda b: SimpleNamespace(projection=lambda: SimpleNamespace(
                getInfo=lambda: {"transform": [CELL, 0, 39.0, 0, -CELL, -8.0]})))
            def mosaic(self):
                image = SimpleNamespace()
                image.select = lambda bands: image
                image.toFloat = lambda: image
                image.unmask = lambda v: image
                return image

        def compute_pixels(params):
            fake.requests.append(params)
            grid = params["grid"]
            row0 = round((-8.0 - grid["affineTransform"]["translateY"]) / CELL)
            h = grid["dimensions"]["height"]
            out = np.zeros((h, grid["dimensions"]["width"]), dtype=[(b, "f4") for b in gh.BANDS])
            for band in gh.BANDS:
                out[band] = values[band][row0:row0 + h]
            return out

        self.ImageCollection = Collection
        self.Geometry = lambda g: g
        self.Feature = lambda *a, **k: None
        self.data = SimpleNamespace(computePixels=compute_pixels)


def test_acquisition_reads_every_band_on_the_native_grid(monkeypatch):
    from app.services.gee import auth
    aoi = _box(39.0, -8.0 - 4 * CELL, 39.0 + 4 * CELL, -8.0)
    values = {band: np.full((4, 4), gh.NODATA, np.float32) for band in gh.BANDS}
    values["RP10_depth"][0, :] = [0.5, 1.0, 2.0, 3.0]
    values["RP500_depth"][:2, :] = 2.0
    values["permanent_water_class"][3, 3] = 1
    footprint = {"type": "Polygon", "coordinates": [[[38.9, -8.1], [39.1, -8.1], [39.1, -7.9], [38.9, -7.9], [38.9, -8.1]]]}
    features = [{"geometry": footprint, "properties": {"index": "ID150_N0_E30", "id": 150, "time_start": 1706918400000}}]
    fake = _FakeEE(features, values)
    monkeypatch.setitem(sys.modules, "ee", fake)
    monkeypatch.setattr(auth, "initialize_gee", lambda *a, **k: None)
    stack = gh.acquire_glofas(aoi)
    assert stack.covered.all() and stack.tiles == [{"index": "ID150_N0_E30", "id": 150, "production_date": "2024-02-03"}]
    assert np.isnan(stack.depth[10][1:]).all() and list(stack.depth[10][0]) == [0.5, 1.0, 2.0, 3.0]
    assert np.isfinite(stack.depth[500][:2]).all() and stack.permanent_water[3, 3] and stack.permanent_water.sum() == 1
    assert fake.requests and fake.requests[0]["grid"]["crsCode"] == "EPSG:4326"
    assert stack.provenance()["asset"] == src.GLOFAS_ASSET and stack.provenance()["resampling"] == "none (native grid)"


def test_acquisition_outside_glofas_raises_a_readable_reason(monkeypatch):
    from app.services.gee import auth
    monkeypatch.setitem(sys.modules, "ee", _FakeEE([], {}))
    monkeypatch.setattr(auth, "initialize_gee", lambda *a, **k: None)
    with pytest.raises(gh.HazardUnavailable, match="outside the GloFAS flood hazard maps"):
        gh.acquire_glofas(AOI_4x4)
