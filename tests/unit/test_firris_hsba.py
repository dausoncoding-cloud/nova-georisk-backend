"""HSBA training label (firris-science-3), pre-registered in plan §1.8a; Chini et al. 2017 equations by number."""
import math

import numpy as np
import pytest

from app.services.firris import hsba
from app.services.firris.hsba import TwoGaussianFit


def mixture(rng, n_low, n_high, low=(-20.0, 1.5), high=(-8.0, 1.5)):
    return np.concatenate([rng.normal(*low, n_low), rng.normal(*high, n_high)])


def fit_with(ashman=3.0, bc=0.999, sr=0.5, water_mean=-20.0):
    edges = np.linspace(-30, 0, 31)
    return TwoGaussianFit((100.0, water_mean, 1.0), (100.0, -8.0, 1.0), ashman, bc, sr, edges, np.ones(30))


def scene(size=256, water_box=(10, 70, 10, 70), seed=7):
    rng = np.random.default_rng(seed)
    baseline = rng.normal(-8, 1.5, (size, size))
    flood = baseline + rng.normal(0, 0.5, (size, size))
    water = np.zeros((size, size), bool)
    r0, r1, c0, c1 = water_box
    water[r0:r1, c0:c1] = True
    flood[water] = rng.normal(-20, 1.5, int(water.sum()))
    return flood, baseline, water


def run(flood, baseline, slope=None, jrc=None, valid=None, **kwargs):
    shape = flood.shape
    return hsba.derive_hsba_label(flood_db=flood, baseline_db=baseline,
                                  slope_deg=np.zeros(shape) if slope is None else slope,
                                  jrc_occurrence=np.zeros(shape) if jrc is None else jrc,
                                  valid_mask=np.ones(shape, bool) if valid is None else valid, **kwargs)


# Pre-registered values (plan §1.8a) --------------------------------------------------------------
def test_pre_registered_values_are_unchanged():
    assert (hsba.MIN_TILE_PX, hsba.MIN_ADMITTED_FRACTION) == (64, 0.5)
    assert (hsba.ASHMAN_D_MIN, hsba.BHATTACHARYYA_MIN, hsba.SURFACE_RATIO_MIN, hsba.WATER_MEAN_MAX_DB) == (2.0, 0.99, 0.1, -15.0)
    assert (hsba.BINS_MIN, hsba.BINS_MAX, hsba.SEED_RATIO) == (30, 200, 0.1)
    assert hsba.TOLERANCE_GRID_DB[0] == 0.0 and hsba.TOLERANCE_GRID_DB[-1] == 10.0 and len(hsba.TOLERANCE_GRID_DB) == 101
    assert hsba.CHANGE_GRID_DB[0] == -10.0 and hsba.CHANGE_GRID_DB[-1] == 0.0 and len(hsba.CHANGE_GRID_DB) == 101
    assert hsba.CONNECTIVITY.sum() == 9 and (hsba.SLOPE_MAX_DEG, hsba.JRC_EXCLUDE_PCT) == (15.0, 90.0)


# Fit and criteria C1-C3 ------------------------------------------------------------------------
def test_lm_fit_recovers_both_components_and_otsu_is_only_the_initial_guess():
    fit = hsba.fit_two_gaussians(mixture(np.random.default_rng(1), 3000, 9000, low=(-19.0, 1.2), high=(-9.0, 2.0)))
    assert fit.low[1] == pytest.approx(-19.0, abs=0.2) and fit.high[1] == pytest.approx(-9.0, abs=0.2)
    assert fit.low[2] == pytest.approx(1.2, abs=0.2) and fit.high[2] == pytest.approx(2.0, abs=0.2)
    assert fit.passes()


def test_c1_is_the_unequal_variance_ashman_d_of_eq_6():
    fit = hsba.fit_two_gaussians(mixture(np.random.default_rng(2), 4000, 4000, low=(-18.0, 1.0), high=(-10.0, 2.0)))
    (a1, m1, s1), (a2, m2, s2) = fit.low, fit.high
    assert fit.ashman_d == pytest.approx(math.sqrt(2) * abs(m2 - m1) / math.sqrt(s1 ** 2 + s2 ** 2))
    assert not fit_with(ashman=2.0).passes() and fit_with(ashman=2.0001).passes()   # strictly > 2 (Eq. 7)


def test_c2_bhattacharyya_rejects_a_histogram_that_is_not_two_gaussians():
    uniform = np.random.default_rng(3).uniform(-25, -5, 8000)
    fit = hsba.fit_two_gaussians(uniform)
    assert fit is None or fit.bhattacharyya <= 0.99 or not fit.passes()
    good = hsba.fit_two_gaussians(mixture(np.random.default_rng(3), 4000, 4000))
    assert good.bhattacharyya > 0.99
    assert not fit_with(bc=0.99).passes() and fit_with(bc=0.9901).passes()        # strictly > .99 (Eq. 9)


def test_c3_surface_ratio_comes_from_fitted_gaussian_areas():
    fit = hsba.fit_two_gaussians(mixture(np.random.default_rng(4), 1500, 9000))
    areas = (fit.low[0] * fit.low[2], fit.high[0] * fit.high[2])
    assert fit.surface_ratio == pytest.approx(min(areas) / max(areas))
    assert fit.surface_ratio == pytest.approx(1500 / 9000, abs=0.03)              # ratio to the OTHER class, not to the tile
    assert not fit_with(sr=0.1).passes() and fit_with(sr=0.1001).passes()          # strictly > .1 (Eq. 11)
    rare = hsba.fit_two_gaussians(mixture(np.random.default_rng(4), 300, 9000))    # 3.3% of the other class
    assert rare is None or not rare.passes()


def test_freedman_diaconis_bins_are_clamped_to_30_200():
    rng = np.random.default_rng(5)
    assert len(hsba.histogram_edges(rng.normal(0, 1, 50))) - 1 == 30
    assert len(hsba.histogram_edges(rng.normal(0, 1, 2_000_000))) - 1 == 200


# Tiles, C4 and acceptance in both images -------------------------------------------------------
def test_quadrants_are_four_non_overlapping_tiles_that_cover_the_parent():
    for rows, cols in ((256, 256), (257, 130)):
        cover = np.zeros((rows, cols), int)
        for r0, c0, h, w in hsba.quadrants(0, 0, rows, cols):
            cover[r0:r0 + h, c0:c0 + w] += 1
        assert (cover == 1).all()
    assert hsba.splittable(128, 128) and not hsba.splittable(127, 200) and not hsba.splittable(200, 127)


def test_minimum_tile_and_admitted_fraction_rules():
    flood, baseline, _ = scene(size=63)
    assert run(flood, baseline).diagnostics["tiles_examined"] == 0                  # smaller than 64 x 64: never evaluated
    flood, baseline, _ = scene(size=128)
    valid = np.zeros((128, 128), bool)
    valid[:, :60] = True                                     # root 46.9% admitted; left quadrants 93.8%, right 0%
    tiles = run(flood, baseline, valid=valid).diagnostics["tiles"]
    assert not tiles[0]["evaluated"] and tiles[0]["admitted_fraction"] == pytest.approx(60 / 128)
    children = tiles[1:5]
    assert [t["evaluated"] for t in children] == [True, False, True, False]   # still split; only >= 50% admitted evaluated


def test_water_in_one_quadrant_is_found_after_splitting_and_descendants_are_skipped():
    flood, baseline, water = scene()
    result = run(flood, baseline)
    tiles = result.diagnostics["tiles"]
    assert not tiles[0]["accepted"]                                                  # whole scene: ~5.5% water, not bimodal
    accepted = [t for t in tiles if t["accepted"]]
    assert accepted and all(t["level"] >= 1 for t in accepted)
    for t in accepted:                                                               # no tile inside an accepted tile is listed
        inside = [u for u in tiles if u is not t and u["row"] >= t["row"] and u["col"] >= t["col"]
                  and u["row"] + u["rows"] <= t["row"] + t["rows"] and u["col"] + u["cols"] <= t["col"] + t["cols"]]
        assert not inside
    label = result.label.astype(bool)
    assert (label & water).sum() / water.sum() > 0.98 and (label & ~water).sum() < 0.01 * water.sum()


def test_c4_rejects_tiles_whose_water_mean_is_above_minus_15_db():
    rng = np.random.default_rng(8)
    baseline = rng.normal(-5, 1.0, (128, 128))
    flood = baseline + rng.normal(0, 0.3, (128, 128))
    dark = np.zeros((128, 128), bool)
    dark[:, :50] = True
    flood[dark] = rng.normal(-13, 1.0, int(dark.sum()))                               # bimodal, but "water" at -13 dB
    result = run(flood, baseline)
    evaluated = [t for t in result.diagnostics["tiles"] if t["evaluated"] and t["flood_image"]]
    assert any(t["flood_image"]["c1"] and t["flood_image"]["c2"] and t["flood_image"]["c3"] and not t["c4"] for t in evaluated)
    assert result.status == hsba.NO_DISTINCT_WATER_CLASS


def test_a_tile_must_be_bimodal_in_both_the_flood_and_the_change_image():
    flood, baseline, water = scene(size=128, water_box=(0, 128, 0, 50))
    baseline[water] = flood[water] + np.random.default_rng(9).normal(0, 0.3, int(water.sum()))  # dark on both dates
    result = run(flood, baseline)
    root = result.diagnostics["tiles"][0]
    assert root["flood_image"]["c1"] and root["flood_image"]["c2"] and root["flood_image"]["c3"]
    assert not root["accepted"] and result.status == hsba.NO_DISTINCT_WATER_CLASS     # no change: permanent water only


# Pooling, seeds, region growing and change detection ---------------------------------------------
def test_pooled_fit_uses_only_pixels_of_accepted_tiles():
    flood, baseline, _ = scene()
    first = run(flood, baseline).diagnostics
    accepted = np.zeros(flood.shape, bool)
    for t in first["tiles"]:
        if t["accepted"]:
            accepted[t["row"]:t["row"] + t["rows"], t["col"]:t["col"] + t["cols"]] = True
    changed = flood.copy()
    changed[~accepted] += np.random.default_rng(10).normal(0, 0.05, int((~accepted).sum()))
    second = run(changed, baseline).diagnostics
    assert second["pooled_fit"] == first["pooled_fit"] and second["thresholds"]["seed_db"] == first["thresholds"]["seed_db"]


def test_seed_threshold_is_where_non_water_reaches_10_percent_of_water():
    fit = hsba.fit_two_gaussians(mixture(np.random.default_rng(11), 4000, 4000))
    y = hsba.seed_threshold(fit)
    centers = (fit.edges[:-1] + fit.edges[1:]) / 2
    previous = centers[(centers >= fit.low[1]) & (centers < y)]
    ratio = lambda v: hsba._gauss(v, *fit.high) / hsba._gauss(v, *fit.low)
    assert y >= fit.low[1] and ratio(y) >= 0.1 and all(ratio(v) < 0.1 for v in previous)


def test_region_growing_is_8_connected_and_needs_a_seed():
    image = np.zeros((7, 7))
    image[1, 1] = -20          # seed
    image[2, 2] = -15          # diagonal neighbour within tolerance: grown (8-connectivity)
    image[5, 5] = -15          # within tolerance but not connected to a seed: not grown
    domain = np.ones((7, 7), bool)
    grown = hsba.grow(image, domain, image <= -18, -14)
    assert grown[1, 1] and grown[2, 2] and not grown[5, 5]


def test_change_detection_removes_only_grown_pixels_without_enough_decrease():
    flood, baseline, water = scene()
    rim = np.zeros(flood.shape, bool)
    rim[70:74, 10:70] = True                       # a strip next to the water, moderately dark on the target date only
    flood[rim] = -15.5
    result = run(flood, baseline)
    t = result.diagnostics["thresholds"]
    label = result.label.astype(bool)
    change = flood - baseline
    grown_only = rim & (flood > t["seed_db"]) & (flood <= t["region_growing_limit_db"])
    assert np.array_equal(label[grown_only], change[grown_only] <= t["change_threshold_db"])
    assert label[water & (flood <= t["seed_db"])].all()                              # seeds are never removed by CD


def test_grid_search_takes_the_joint_minimum_within_the_pre_registered_ranges():
    flood, baseline, _ = scene()
    t = run(flood, baseline).diagnostics["thresholds"]
    assert 0.0 <= t["tolerance_db"] <= 10.0 and -10.0 <= t["change_threshold_db"] <= 0.0
    assert round(t["tolerance_db"] * 10) == t["tolerance_db"] * 10 and round(t["change_threshold_db"] * 10) == pytest.approx(t["change_threshold_db"] * 10)


# Exclusions and fallback ------------------------------------------------------------------------
def test_baseline_water_jrc_and_slope_exclusions():
    flood, baseline, water = scene()
    permanent = np.zeros(flood.shape, bool)
    permanent[100:120, 100:120] = True
    flood[permanent] = -20
    baseline[permanent] = -20                                        # dark on both dates: removed as baseline water (p. 6984)
    jrc = np.zeros(flood.shape)
    jrc[10:20, 10:70] = 95                                           # JRC >= 90%: removed at the end
    slope = np.zeros(flood.shape)
    slope[40:50, 10:70] = 20                                         # steep: never a seed, never grown through
    result = run(flood, baseline, slope=slope, jrc=jrc)
    label = result.label.astype(bool)
    assert not label[permanent].any() and not label[10:20, 10:70].any() and not label[40:50, 10:70].any()
    assert label[25:35, 10:70].mean() > 0.99 and label[55:65, 10:70].mean() > 0.99   # both sides of the steep band (noise tail aside)
    counts = result.diagnostics["pixel_counts"]
    assert counts["baseline_water_removed"] >= permanent.sum() and counts["jrc_removed"] > 0


def test_steep_band_blocks_growth_between_regions():
    image = np.full((5, 9), -15.0)
    image[:, 0] = -20                       # seed column
    domain = np.ones((5, 9), bool)
    domain[:, 4] = False                    # steep column: outside the growth domain
    grown = hsba.grow(image, domain, (image <= -18) & domain, -14)
    assert grown[:, :4].all() and not grown[:, 4:].any()


def test_no_flood_scene_falls_back_to_no_distinct_water_class():
    rng = np.random.default_rng(12)
    baseline = rng.normal(-8, 1.5, (256, 256))
    result = run(baseline + rng.normal(0, 0.5, (256, 256)), baseline)
    assert result.status == hsba.NO_DISTINCT_WATER_CLASS and result.label.sum() == 0
    assert result.diagnostics["tiles_examined"] > 0 and result.diagnostics["tiles_accepted"] == 0
    assert "thresholds" not in result.diagnostics                     # no threshold of any kind


def test_diagnostics_record_parameters_deviations_limitation_and_runtime():
    flood, baseline, _ = scene()
    d = run(flood, baseline).diagnostics
    assert d["status"] == "labelled" and d["runtime_s"] >= 0 and len(d["deviations"]) == 7
    assert "pp. 6982, 6985" in d["limitation"] and d["parameters"]["min_tile_px"] == 64
    assert hsba.rule_text(d).startswith("HSBA (Chini et al. 2017")


# Workflow integration ---------------------------------------------------------------------------
def _stack(flood, baseline, features):
    from rasterio.transform import from_origin

    from app.services.gee.firris_pipeline import GEEFeatureStack
    size = flood.shape[0]
    rows, _ = np.indices(flood.shape)
    return GEEFeatureStack(
        feature_layers={name: layer for name, layer in {"sar_change": (flood - baseline).astype("float32"),
                        "slope": np.zeros(flood.shape, "float32"), "rainfall": (rows / size).astype("float32")}.items() if name in features},
        label_layer=np.zeros(flood.shape, np.uint8), valid_mask=np.ones(flood.shape, bool), transform=from_origin(36, -1, 0.01, 0.01),
        crs="EPSG:4326", quality={"status": "passed", "valid_pixel_coverage_pct": 100.0}, provenance={"label_source": "x"},
        source_rasters={"source_sar_target": flood.astype("float32"), "source_sar_baseline": baseline.astype("float32"),
                        "jrc_occurrence": np.zeros(flood.shape, "float32")})


def _workflow(tmp_path, monkeypatch, stack, features):
    from app.services.firris import workflow
    from app.services.gee import firris_pipeline
    monkeypatch.setattr(firris_pipeline, "fetch_feature_stack", lambda *a, **k: stack)
    size = stack.label_layer.shape[0] * 0.01
    return workflow.run_satellite_workflow(
        {"source": {"provider": "gee", "features": features},
         "sampling": {"sample_size": 300, "min_per_class": 20, "train_fraction": 0.7, "random_seed": 3},
         "model": {"algorithm": "random_forest", "version": "test", "n_estimators": 10}},
        {"crs": "EPSG:4326", "bounding_box": {"west": 36, "south": -1 - size, "east": 36 + size, "north": -1}},
        {"type": "Polygon", "coordinates": [[[36, -1 - size], [36 + size, -1 - size], [36 + size, -1], [36, -1], [36, -1 - size]]]},
        tmp_path)


def test_hsba_label_trains_the_model_and_lands_in_provenance(tmp_path, monkeypatch):
    flood, baseline, water = scene(size=128, water_box=(0, 128, 0, 40))
    output = _workflow(tmp_path, monkeypatch, _stack(flood, baseline, ["sar_change", "slope", "rainfall"]), ["sar_change", "slope", "rainfall"])
    rule = output.provenance["label_rule"]
    assert rule["status"] == "labelled" and rule["tiles"] and output.provenance["label_source"].startswith("HSBA")
    assert output.quality["hsba_label"]["tiles_accepted"] >= 1 and "tiles" not in output.quality["hsba_label"]
    observed = output.samples["observed_label"].to_numpy()
    rows, cols = output.samples["pixel_row"].to_numpy(), output.samples["pixel_col"].to_numpy()
    assert (observed == water[rows, cols]).mean() > 0.98                                  # samples carry the HSBA label


def test_no_distinct_water_class_ends_the_run_with_an_allow_listed_message(tmp_path, monkeypatch):
    from app.services.firris.user_messages import public_error_summary
    from app.services.gee.firris_pipeline import FIRRISQualityError
    rng = np.random.default_rng(13)
    baseline = rng.normal(-8, 1.5, (128, 128))
    with pytest.raises(FIRRISQualityError) as caught:
        _workflow(tmp_path, monkeypatch, _stack(baseline + rng.normal(0, .5, (128, 128)), baseline, ["sar_change", "slope"]), ["sar_change", "slope"])
    assert "NO_DISTINCT_WATER_CLASS" in str(caught.value) and public_error_summary(caught.value) == str(caught.value)
    assert caught.value.quality_record["failure_code"] == "NO_DISTINCT_WATER_CLASS"
    assert "tiles" not in caught.value.quality_record["hsba_label"]


def test_missing_slope_feature_fails_closed(tmp_path, monkeypatch):
    from app.services.firris.user_messages import public_error_summary
    from app.services.gee.firris_pipeline import FIRRISQualityError
    flood, baseline, _ = scene(size=128, water_box=(0, 128, 0, 40))
    with pytest.raises(FIRRISQualityError, match="requires the slope feature") as caught:
        _workflow(tmp_path, monkeypatch, _stack(flood, baseline, ["sar_change", "rainfall"]), ["sar_change", "rainfall"])
    assert public_error_summary(caught.value) == str(caught.value)


def test_report_states_the_hsba_limitation_and_method(tmp_path_factory):
    from tests.unit._report_run import report_run
    _, _, _, text, _, docx_text = report_run(tmp_path_factory)
    for body in (text, docx_text):
        flat = " ".join(body.split())
        assert "flooded vegetation and urban areas" in flat and "pp. 6982, 6985" in flat
        assert "HSBA (Chini et al. 2017" in flat and "Deviations from the published method" in flat
