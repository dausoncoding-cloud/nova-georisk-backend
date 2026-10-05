"""Exact-cell spatial support and the unchanged multiplicative FRI formula."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pyproj import Transformer

from app.schemas.source_bindings import RasterGrid
from app.services.firas.risk import compute_fri
from app.services.source_data.readiness import SourceNotReady
from app.services.source_data.risk import assign_fii_to_exact_cells


def _geometry(west, east, south=0, north=100):
    back = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    coords = [list(back.transform(x, y)) for x, y in
              ((west, south), (east, south), (east, north), (west, north), (west, south))]
    return {"type": "Polygon", "coordinates": [coords]}


def test_fri_is_exactly_hazard_times_exposure_times_fii_not_vulnerability():
    h = pd.Series([0.8, 0.3])
    e = pd.Series([0.5, 0.7])
    fii = pd.Series([0.2, 0.9])
    fvi = pd.Series([0.9, 0.1])
    result = compute_fri(h, e, fii)
    np.testing.assert_allclose(result.to_numpy(), (h * e * fii).to_numpy())
    assert not np.allclose(result.to_numpy(), (h * e * fvi).to_numpy())


def test_fii_assignment_rejects_cells_crossing_unit_boundaries():
    grid = RasterGrid(crs="EPSG:3857", west=0, south=0, east=200, north=100, width=2, height=1)
    aoi = _geometry(0, 200)
    mask = np.array([[True, True]])
    units = {"west": _geometry(0, 100), "east": _geometry(100, 200)}
    assigned, records = assign_fii_to_exact_cells(grid, aoi, mask, units, {"west": 0.2, "east": 0.8})
    np.testing.assert_allclose(assigned, [[0.2, 0.8]])
    assert [record[2] for record in records] == ["west", "east"]
    with pytest.raises(SourceNotReady, match="crosses"):
        assign_fii_to_exact_cells(grid, aoi, mask,
                                  {"west": _geometry(0, 50), "east": _geometry(50, 200)},
                                  {"west": 0.2, "east": 0.8})
    with pytest.raises(SourceNotReady, match="lacks"):
        assign_fii_to_exact_cells(grid, aoi, mask,
                                  {"west": _geometry(0, 90), "east": _geometry(110, 200)},
                                  {"west": 0.2, "east": 0.8})
    with pytest.raises(SourceNotReady, match="differ"):
        assign_fii_to_exact_cells(grid, aoi, mask, units, {"west": 0.2})
