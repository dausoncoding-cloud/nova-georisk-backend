"""Plan 4.6 calibration: the preflight size estimate never falls below Earth Engine's request size.

Measured 2026-11-14 with the dev key (over-limit probe + 1-byte grid probe on the exact pipeline image):
Earth Engine counts 93.000 bytes per output pixel for the current band contract (5 features + 3 source
+ 4 reference bands, each with a validity band). The output grid is the AOI bbox snapped to the global
EPSG:4326 pixel grid at the requested scale.
"""
import math
import random

import pytest

from app.services.firris.preflight import BYTES_PER_PIXEL, METRES_PER_DEGREE, capacity_estimate
from app.services.gee.firris_pipeline import DEFAULT_FEATURES, REFERENCE_BANDS, SOURCE_BANDS

MEASURED = [  # (bounds, scale, Earth Engine grid px, Earth Engine request bytes)
    ((38.92, -7.99, 39.01, -7.90), 30, 112_225, 10_436_925),   # Rufiji, 335x335
    ((38.92, -7.99, 39.01, -7.90), 60, 28_224, 2_624_832),     # Rufiji, 168x168
    ((34.70, -5.85, 34.80, -5.75), 30, 138_384, 12_869_712),   # Manyoni 0.1°, 372x372
    ((38.92, -7.99, 39.01, -7.90), 7, 2_052_056, 190_841_208),  # over-limit probe
    ((34.70, -5.85, 34.80, -5.75), 7, 2_531_281, 235_409_133),  # over-limit probe
]


def _ee_grid(bounds, scale):
    """Earth Engine's output grid: the bbox snapped outward to the global pixel grid."""
    step = scale / METRES_PER_DEGREE
    west, south, east, north = bounds
    return (math.ceil(east / step) - math.floor(west / step)) * (math.ceil(north / step) - math.floor(south / step))


@pytest.mark.parametrize("bounds, scale, grid_px, request_bytes", MEASURED)
def test_estimate_is_never_below_measured_earth_engine_requests(bounds, scale, grid_px, request_bytes):
    estimate = capacity_estimate(bounds, scale)
    assert _ee_grid(bounds, scale) == grid_px  # the snapping model reproduces every measured grid
    assert estimate["bbox_pixels"] >= grid_px and estimate["estimated_request_bytes"] >= request_bytes
    assert request_bytes == grid_px * BYTES_PER_PIXEL  # 93 B/px is exact for this contract


def test_pixel_estimate_bounds_the_snapped_grid_for_any_box_and_scale():
    rng = random.Random(20261114)
    for _ in range(5000):
        west, south = rng.uniform(-180, 179), rng.uniform(-80, 79)
        bounds = (west, south, west + rng.uniform(1e-4, 1.5), south + rng.uniform(1e-4, 1.5))
        scale = rng.choice([10, 20, 30, 45, 60, 90, 120, 250, 500])
        assert capacity_estimate(bounds, scale)["bbox_pixels"] >= _ee_grid(bounds, scale), (bounds, scale)


def test_estimate_scales_with_the_inverse_square_of_resolution():
    bounds = (38.92, -7.99, 39.01, -7.90)
    at30, at60 = (capacity_estimate(bounds, s)["estimated_request_bytes"] for s in (30, 60))
    assert 3.8 < at30 / at60 < 4.2


def test_bytes_per_pixel_is_tied_to_the_calibrated_band_contract():
    # Recalibrate BYTES_PER_PIXEL (see module docstring) whenever this contract changes.
    assert BYTES_PER_PIXEL == 93
    assert DEFAULT_FEATURES == ["sar_vv_target", "sar_change", "elevation", "slope", "rainfall"]
    assert SOURCE_BANDS == ["source_sar_baseline", "source_sar_target", "label"]
    assert REFERENCE_BANDS == ["jrc_occurrence", "source_mndwi_target", "source_mndwi_baseline", "optical_reference"]
