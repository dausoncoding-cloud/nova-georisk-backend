import pytest

from app.utils.geo_utils import compute_aoi_stats
from app.utils.validators import validate_aoi_geometry

DAR_ES_SALAAM_SQUARE_KM = {
    "type": "Polygon",
    "coordinates": [[
        [39.2000, -6.8000],
        [39.2090, -6.8000],
        [39.2090, -6.8090],
        [39.2000, -6.8090],
        [39.2000, -6.8000],
    ]],
}


def test_validate_aoi_geometry_accepts_valid_polygon():
    validate_aoi_geometry(DAR_ES_SALAAM_SQUARE_KM)  # should not raise


def test_compute_aoi_stats_returns_expected_keys():
    stats = compute_aoi_stats(DAR_ES_SALAAM_SQUARE_KM)
    assert set(stats) == {"area_m2", "area_hectares", "area_km2", "perimeter_m"}


def test_compute_aoi_stats_area_close_to_one_km2():
    stats = compute_aoi_stats(DAR_ES_SALAAM_SQUARE_KM)
    assert 0.9 < stats["area_km2"] < 1.1


def test_compute_aoi_stats_rejects_non_polygon():
    import pytest

    point = {"type": "Point", "coordinates": [39.2, -6.8]}
    with pytest.raises(ValueError):
        compute_aoi_stats(point)


def test_compute_aoi_stats_handles_multipolygon():
    single_poly = {
        "type": "Polygon",
        "coordinates": [[[39.20, -6.80], [39.21, -6.80], [39.21, -6.81], [39.20, -6.81], [39.20, -6.80]]],
    }
    single_stats = compute_aoi_stats(single_poly)

    multi = {
        "type": "MultiPolygon",
        "coordinates": [
            single_poly["coordinates"],
            [[[39.30, -6.90], [39.31, -6.90], [39.31, -6.91], [39.30, -6.91], [39.30, -6.90]]],
        ],
    }
    multi_stats = compute_aoi_stats(multi)

    # Two identically-sized polygons -> combined area should be ~2x one of them
    assert multi_stats["area_km2"] == pytest.approx(2 * single_stats["area_km2"], rel=0.05)
    assert multi_stats["perimeter_m"] == pytest.approx(2 * single_stats["perimeter_m"], rel=0.05)


def test_compute_aoi_stats_polygon_with_hole():
    polygon_with_hole = {
        "type": "Polygon",
        "coordinates": [
            [[39.20, -6.80], [39.22, -6.80], [39.22, -6.82], [39.20, -6.82], [39.20, -6.80]],  # exterior
            [[39.205, -6.805], [39.215, -6.805], [39.215, -6.815], [39.205, -6.815], [39.205, -6.805]],  # hole
        ],
    }
    stats_with_hole = compute_aoi_stats(polygon_with_hole)

    solid_polygon = {
        "type": "Polygon",
        "coordinates": [polygon_with_hole["coordinates"][0]],
    }
    stats_solid = compute_aoi_stats(solid_polygon)

    # The hole should reduce net area but the exterior+hole perimeter is
    # larger than the exterior-only perimeter.
    assert stats_with_hole["area_m2"] < stats_solid["area_m2"]
    assert stats_with_hole["perimeter_m"] > stats_solid["perimeter_m"]
    reversed_hole = {"type": "Polygon", "coordinates": [
        polygon_with_hole["coordinates"][0],
        list(reversed(polygon_with_hole["coordinates"][1])),
    ]}
    assert compute_aoi_stats(reversed_hole)["area_m2"] == pytest.approx(stats_with_hole["area_m2"])
