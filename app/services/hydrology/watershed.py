"""
DEM-based terrain & watershed analysis — Doc 1 §1.4 (Slope) and the
"HYDROLOGICAL AND WATERSHED MODELING" section (flow direction, flow
accumulation, TWI, drainage density).

Operates on a raster DEM as a 2D numpy array. D8 flow routing (each
cell drains to whichever of its 8 neighbours has the steepest downhill
gradient) is the standard, tractable way to compute flow direction and
accumulation on a grid, and is what "most GIS software computes
automatically" per the spec.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# D8 neighbour offsets in ESRI-style clockwise order, with their bit-flag codes.
# (row_offset, col_offset, code)
_D8_NEIGHBOURS = [
    (0, 1, 1),    # E
    (1, 1, 2),    # SE
    (1, 0, 4),    # S
    (1, -1, 8),   # SW
    (0, -1, 16),  # W
    (-1, -1, 32), # NW
    (-1, 0, 64),  # N
    (-1, 1, 128), # NE
]


def compute_slope(dem: np.ndarray, cell_size: float = 1.0, unit: str = "degrees") -> np.ndarray:
    """
    Slope via the finite-difference gradient — Doc 1 §1.4:
        Slope(deg) = arctan( sqrt((dz/dx)^2 + (dz/dy)^2) )
        Slope(%)   = sqrt((dz/dx)^2 + (dz/dy)^2) * 100
    """
    dz_dy, dz_dx = np.gradient(dem, cell_size)
    gradient_magnitude = np.sqrt(dz_dx**2 + dz_dy**2)

    if unit == "percent":
        return gradient_magnitude * 100
    if unit == "degrees":
        return np.degrees(np.arctan(gradient_magnitude))
    raise ValueError("unit must be 'degrees' or 'percent'.")


def normalize_slope_index(slope: np.ndarray) -> np.ndarray:
    """S_i = (S_max - S) / (S_max - S_min) — Doc 1 §1.4 normalization (note: inverted convention as given)."""
    s_min, s_max = slope.min(), slope.max()
    if s_max == s_min:
        return np.zeros_like(slope)
    return (s_max - slope) / (s_max - s_min)


def compute_flow_direction(dem: np.ndarray) -> np.ndarray:
    """
    D8 flow direction: each cell points to its steepest-descent
    neighbour (ESRI-style bit-flag codes: E=1, SE=2, S=4, SW=8, W=16,
    NW=32, N=64, NE=128). Edge cells and local sinks (no downhill
    neighbour) get code 0 (no outflow / undefined).
    """
    rows, cols = dem.shape
    flow_dir = np.zeros_like(dem, dtype=np.int16)

    for r in range(rows):
        for c in range(cols):
            best_drop = 0.0
            best_code = 0
            for dr, dc, code in _D8_NEIGHBOURS:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    distance = np.sqrt(dr**2 + dc**2)
                    drop = (dem[r, c] - dem[nr, nc]) / distance
                    if drop > best_drop:
                        best_drop = drop
                        best_code = code
            flow_dir[r, c] = best_code

    return flow_dir


def compute_flow_accumulation(dem: np.ndarray, flow_dir: np.ndarray) -> np.ndarray:
    """
    FA(i) = sum of contributing upstream area, Doc 1's watershed
    section. Every cell starts with an accumulation of 1 (itself);
    cells are processed from highest to lowest elevation so that each
    cell's accumulation is finalized before it's passed downstream —
    this correctly handles arbitrary DEM shapes without recursion.
    """
    rows, cols = dem.shape
    accumulation = np.ones_like(dem, dtype=np.float64)

    code_to_offset = {code: (dr, dc) for dr, dc, code in _D8_NEIGHBOURS}
    order = np.dstack(np.unravel_index(np.argsort(-dem, axis=None), dem.shape))[0]

    for r, c in order:
        code = flow_dir[r, c]
        if code == 0:
            continue
        dr, dc = code_to_offset[code]
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols:
            accumulation[nr, nc] += accumulation[r, c]

    return accumulation


def compute_twi(dem: np.ndarray, flow_accumulation: np.ndarray, cell_size: float = 1.0) -> np.ndarray:
    """
    Topographic Wetness Index — TWI = ln(A_s / tan(beta)).
    A_s (specific catchment area) is approximated as flow_accumulation
    x cell_area / cell_size (contour length approximation, standard
    grid-based TWI practice). Slope beta is clipped to a small minimum
    to avoid tan(0) blowing up on perfectly flat cells.
    """
    slope_deg = compute_slope(dem, cell_size=cell_size, unit="degrees")
    slope_rad = np.radians(np.clip(slope_deg, a_min=0.1, a_max=None))  # avoid tan(0)

    specific_catchment_area = flow_accumulation * cell_size  # As ~ FA * cell_size (per unit contour width)
    return np.log(specific_catchment_area / np.tan(slope_rad))


@dataclass
class DrainageDensityResult:
    drainage_density: float  # Dd = sum(Ls) / A, in (length unit)/(area unit)
    normalized_index: float | None  # D_i, only when min/max across basins is supplied


def compute_drainage_density(
    stream_mask: np.ndarray,
    cell_size: float,
    dd_min: float | None = None,
    dd_max: float | None = None,
) -> DrainageDensityResult:
    """
    Dd = sum(Ls) / A — Doc 1 "Drainage Density (Landscape Dissection
    Index)". `stream_mask` is a boolean raster of channel cells (e.g.
    thresholded flow accumulation); total stream length is
    approximated as (number of stream cells x cell_size), basin area
    as (total cells x cell_size^2) — the standard grid-based
    approximation.
    """
    total_stream_length = float(np.sum(stream_mask)) * cell_size
    basin_area = stream_mask.size * (cell_size**2)
    dd = total_stream_length / basin_area if basin_area > 0 else 0.0

    normalized = None
    if dd_min is not None and dd_max is not None and dd_max > dd_min:
        normalized = (dd - dd_min) / (dd_max - dd_min)

    return DrainageDensityResult(drainage_density=dd, normalized_index=normalized)
