from datetime import datetime, timedelta

import pytest

from app.utils.validators import validate_aoi_geometry, validate_date_range


def test_validate_aoi_geometry_rejects_self_intersecting_polygon():
    bowtie = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
    with pytest.raises(ValueError, match="Invalid AOI geometry"):
        validate_aoi_geometry(bowtie)


def test_validate_aoi_geometry_rejects_non_polygon_type():
    point = {"type": "Point", "coordinates": [0, 0]}
    with pytest.raises(ValueError, match="must be Polygon or MultiPolygon"):
        validate_aoi_geometry(point)


def test_validate_aoi_geometry_accepts_multipolygon():
    multi = {
        "type": "MultiPolygon",
        "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]],
    }
    validate_aoi_geometry(multi)  # should not raise


def test_validate_date_range_accepts_valid_range():
    start = datetime(2026, 1, 1)
    end = datetime(2026, 6, 1)
    validate_date_range(start, end)  # should not raise


def test_validate_date_range_rejects_equal_dates():
    same = datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="earlier than"):
        validate_date_range(same, same)


def test_validate_date_range_rejects_reversed_range():
    start = datetime(2026, 6, 1)
    end = start - timedelta(days=30)
    with pytest.raises(ValueError):
        validate_date_range(start, end)
