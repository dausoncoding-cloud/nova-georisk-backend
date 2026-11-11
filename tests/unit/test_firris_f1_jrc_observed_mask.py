"""F1: JRC never-water is 0% occurrence inside the JRC observation footprint (Metadata valid_obs > 0).

Evidence for the mask choice: verification §11.1 (2026-11-11). YearlyHistory also masks
never-water pixels, so it cannot bound the unmask; Metadata.valid_obs can.

The numpy-backed fake below reproduces Earth Engine mask semantics for the few image
operations used, so pixel-level behaviour can be checked without a provider session.
Synthetic fixtures prove software behaviour, not field accuracy.
"""
import inspect

import numpy as np
import pytest
from rasterio.transform import from_origin

from app.services.gee import firris_pipeline as pipeline
from app.services.gee import screening_pipeline
from app.services.gee.firris_contracts import assess_pixels

AOI = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
GRID = from_origin(0, 2, 1, 1)


class FakeImage:
    """Single-band image with Earth Engine-style masks (masked = no data)."""

    def __init__(self, data):
        self.data = np.ma.array(data, dtype="float64")

    def _cmp(self, op, value):
        other = value.data if isinstance(value, FakeImage) else value
        result = np.ma.array(op(self.data.filled(np.nan), np.ma.filled(other, np.nan)).astype("float64"),
                             mask=np.ma.getmaskarray(self.data) | np.ma.getmaskarray(other))
        return FakeImage(result)

    def select(self, name):
        return self

    def rename(self, name):
        return self

    def clip(self, geometry):
        return self

    def unmask(self, value=0, sameFootprint=True):
        return FakeImage(np.ma.array(self.data.filled(value), mask=False))

    def updateMask(self, mask_image):
        mask = np.ma.getmaskarray(mask_image.data) | (mask_image.data.filled(0) == 0)
        return FakeImage(np.ma.array(self.data.filled(np.nan), mask=np.ma.getmaskarray(self.data) | mask))

    def gt(self, value):
        return self._cmp(np.greater, value)

    def lt(self, value):
        return self._cmp(np.less, value)

    def lte(self, value):
        return self._cmp(np.less_equal, value)

    def And(self, other):
        return self._cmp(lambda a, b: np.logical_and(a != 0, b != 0), other)


def grid(values):
    data = [[np.nan if v is None else v for v in row] for row in values]
    mask = [[v is None for v in row] for row in values]
    return np.ma.array(data, mask=mask, dtype="float64")


# 2x2 AOI: three dry-land cells JRC observed but never saw water (occurrence masked,
# valid_obs > 0) and one cell JRC never observed (valid_obs = 0).
OCCURRENCE = grid([[None, None], [None, None]])
VALID_OBS = grid([[300, 281], [383, 0]])


def corrected(occurrence=OCCURRENCE, valid_obs=VALID_OBS):
    return pipeline.jrc_occurrence_within_observed_footprint(FakeImage(occurrence), FakeImage(valid_obs)).data


def test_dry_land_with_valid_observations_becomes_zero_percent_occurrence():
    result = corrected()
    assert not result.mask[0, 0] and not result.mask[0, 1] and not result.mask[1, 0]
    assert result[0, 0] == result[0, 1] == result[1, 0] == 0


def test_pixel_with_zero_valid_observations_stays_nodata():
    assert corrected().mask[1, 1]


def test_pixel_with_masked_valid_observations_stays_nodata():
    result = corrected(grid([[None, None], [None, None]]), grid([[300, None], [300, 300]]))
    assert result.mask[0, 1] and not result.mask[0, 0]


def test_observed_occurrence_values_are_preserved():
    result = corrected(grid([[95, None], [40, None]]), grid([[300, 300], [300, 0]]))
    assert result[0, 0] == 95 and result[1, 0] == 40 and result[0, 1] == 0 and result.mask[1, 1]


def test_label_is_defined_on_observed_dry_land_and_nodata_where_unobserved():
    water = pipeline.jrc_occurrence_within_observed_footprint(FakeImage(OCCURRENCE), FakeImage(VALID_OBS))
    sar_drop = FakeImage(grid([[-2.0, -0.5], [-2.0, -2.0]]))
    flat = FakeImage(grid([[2.0, 2.0], [20.0, 2.0]]))
    label = screening_pipeline.screen_binary_flood_extent(sar_drop, flat, water).data
    # (0,0) SAR drop on flat never-water land -> candidate; (0,1) no drop -> 0; (1,0) steep -> 0.
    assert label[0, 0] == 1 and label[0, 1] == 0 and label[1, 0] == 0
    assert not label.mask[:1].any() and not label.mask[1, 0]
    assert label.mask[1, 1]


def _stack(label):
    feature = np.ma.array(np.ones((2, 2)), mask=False)
    return np.ma.array([feature, label])


def test_pixel_admission_counts_observed_dry_land_and_excludes_unobserved_cell():
    water = pipeline.jrc_occurrence_within_observed_footprint(FakeImage(OCCURRENCE), FakeImage(VALID_OBS))
    label = screening_pipeline.screen_binary_flood_extent(
        FakeImage(grid([[-2.0, -2.0], [-2.0, -2.0]])), FakeImage(grid([[2.0, 2.0], [2.0, 2.0]])), water).data

    valid, qa = assess_pixels(_stack(label), AOI, GRID, "EPSG:4326", 70)

    assert qa["aoi_cells"] == 4 and qa["valid_aoi_cells"] == 3 and qa["missing_aoi_cells"] == 1
    assert qa["valid_pixel_coverage_pct"] == 75
    assert valid[0, 0] and valid[0, 1] and valid[1, 0] and not valid[1, 1]


def test_raw_occurrence_reproduces_the_f1_defect_on_the_same_fixture():
    # Regression anchor: the pre-correction label consumed raw occurrence, so the same
    # dry-land fixture had 0% coverage and failed the unchanged 70% gate.
    label = screening_pipeline.screen_binary_flood_extent(
        FakeImage(grid([[-2.0, -2.0], [-2.0, -2.0]])), FakeImage(grid([[2.0, 2.0], [2.0, 2.0]])),
        FakeImage(OCCURRENCE)).data
    with pytest.raises(ValueError, match="coverage"):
        assess_pixels(_stack(label), AOI, GRID, "EPSG:4326", 70)


def test_coverage_gate_is_unchanged():
    water = pipeline.jrc_occurrence_within_observed_footprint(
        FakeImage(OCCURRENCE), FakeImage(grid([[300, 0], [300, 0]])))
    label = screening_pipeline.screen_binary_flood_extent(
        FakeImage(grid([[-2.0, -2.0], [-2.0, -2.0]])), FakeImage(grid([[2.0, 2.0], [2.0, 2.0]])), water).data
    with pytest.raises(ValueError, match="below the configured 70.00% threshold"):
        assess_pixels(_stack(label), AOI, GRID, "EPSG:4326", 70)


def test_firris_mask_path_uses_metadata_valid_obs_and_never_yearly_history():
    source = inspect.getsource(pipeline)
    assert pipeline.JRC_OBSERVATION_ASSET == "JRC/GSW1_4/Metadata"
    assert "JRC/GSW1_4/YearlyHistory" not in source
    helper = inspect.getsource(pipeline.jrc_occurrence_within_observed_footprint)
    assert "valid_obs" in helper or "gt(0)" in helper
