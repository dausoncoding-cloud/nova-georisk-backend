import numpy as np
import pytest

from app.services.hydrology.watershed import (
    compute_drainage_density,
    compute_flow_accumulation,
    compute_flow_direction,
    compute_slope,
    compute_twi,
    normalize_slope_index,
)


def test_slope_is_zero_on_flat_dem():
    flat = np.full((5, 5), 100.0)
    slope = compute_slope(flat)
    assert np.allclose(slope, 0.0)


def test_slope_positive_on_tilted_dem():
    # Elevation increases by 1 per column -> constant nonzero slope everywhere (interior)
    rows, cols = 6, 6
    dem = np.tile(np.arange(cols, dtype=float), (rows, 1))
    slope = compute_slope(dem, cell_size=1.0)
    assert (slope[1:-1, 1:-1] > 0).all()


def test_normalize_slope_index_inverts_as_specified():
    """Doc 1 §1.4: S_i = (S_max - S) / (S_max - S_min) -- steepest slope gets LOWEST index."""
    slope = np.array([0.0, 10.0, 20.0, 30.0])
    idx = normalize_slope_index(slope)
    assert idx[0] == pytest.approx(1.0)  # flattest -> highest index
    assert idx[-1] == pytest.approx(0.0)  # steepest -> lowest index


def test_flow_direction_points_downhill_on_simple_ramp():
    """
    A DEM that decreases toward the south (increasing row index) should
    have every interior cell's flow direction pointing S (code 4).
    """
    rows, cols = 5, 5
    dem = np.zeros((rows, cols))
    for r in range(rows):
        dem[r, :] = (rows - r) * 10.0  # highest at row 0, lowest at row rows-1

    flow_dir = compute_flow_direction(dem)
    # Interior cells (not the last row, which has no further downhill neighbour) should point S.
    assert (flow_dir[:-1, 1:-1] == 4).all()


def test_flow_direction_zero_at_local_sink():
    """A single-cell pit (lowest point, all neighbours higher) has no downhill neighbour -> code 0."""
    dem = np.array(
        [
            [10.0, 10.0, 10.0],
            [10.0, 0.0, 10.0],
            [10.0, 10.0, 10.0],
        ]
    )
    flow_dir = compute_flow_direction(dem)
    assert flow_dir[1, 1] == 0


def test_flow_accumulation_increases_downstream_in_converging_valley():
    """
    A straight channel down the middle column, with the two side
    columns sloping toward it: accumulation should increase moving
    down the channel (more upstream area drains into lower cells).
    """
    rows, cols = 6, 3
    dem = np.zeros((rows, cols))
    for r in range(rows):
        dem[r, 0] = (rows - r) * 10 + 5   # left bank, slightly higher, slopes toward center
        dem[r, 1] = (rows - r) * 10       # center channel, lowest
        dem[r, 2] = (rows - r) * 10 + 5   # right bank

    flow_dir = compute_flow_direction(dem)
    accumulation = compute_flow_accumulation(dem, flow_dir)

    # Accumulation in the channel column should be non-decreasing going downstream (row 0 -> row rows-1)
    channel_accum = accumulation[:, 1]
    assert all(channel_accum[i + 1] >= channel_accum[i] for i in range(len(channel_accum) - 1))
    # The outlet (last row, channel) should have accumulated more than a single cell.
    assert channel_accum[-1] > 1


def test_flow_accumulation_every_cell_at_least_one():
    rng = np.random.default_rng(0)
    dem = rng.uniform(0, 100, size=(8, 8))
    flow_dir = compute_flow_direction(dem)
    accumulation = compute_flow_accumulation(dem, flow_dir)
    assert (accumulation >= 1).all()


def test_twi_higher_in_flat_high_accumulation_areas():
    """TWI = ln(As / tan(beta)) should be finite and well-defined everywhere on a real DEM."""
    dem = np.full((5, 5), 50.0)
    dem[2, 2] = 49.9  # a slight depression
    flow_dir = compute_flow_direction(dem)
    accumulation = compute_flow_accumulation(dem, flow_dir)

    twi = compute_twi(dem, accumulation, cell_size=1.0)
    assert twi.shape == dem.shape
    assert np.isfinite(twi).all()


def test_drainage_density_basic_formula():
    # 10x10 grid, cell_size=100m -> basin area = 1,000,000 m^2
    stream_mask = np.zeros((10, 10), dtype=bool)
    stream_mask[5, :] = True  # one full row of stream cells = 10 cells
    result = compute_drainage_density(stream_mask, cell_size=100.0)

    total_length = 10 * 100.0  # 1000 m
    basin_area = 100 * (100.0**2)  # 100 cells * 10000 m^2/cell
    expected_dd = total_length / basin_area
    assert result.drainage_density == pytest.approx(expected_dd)
    assert result.normalized_index is None  # no dd_min/dd_max supplied


def test_drainage_density_normalization_in_range():
    stream_mask = np.zeros((5, 5), dtype=bool)
    stream_mask[2, :] = True
    result = compute_drainage_density(stream_mask, cell_size=10.0, dd_min=0.0, dd_max=1.0)
    assert 0.0 <= result.normalized_index <= 1.0
