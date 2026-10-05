import numpy as np
import pytest

from app.services.firris.area_statistics import raster_area_statistics
from app.services.maps.export import RasterSpec


def test_geodesic_flood_area_and_percent_exclude_invalid_cells():
    spec = RasterSpec.from_bbox(36, -2, 37, -1, 2, 2, crs_epsg=4326)
    values = np.array([[1, 0], [1, 1]], dtype=np.uint8)
    result = raster_area_statistics(values, spec, nodata_mask=np.array([[True, True], [True, False]]))
    assert result["method"] == "ellipsoidal_geodesic"
    assert result["valid_cells"] == 3
    assert result["valid_area_m2"] > 0
    assert 60 < result["flooded_percent_of_valid"] < 70
    assert result["valid_area_ha"] == pytest.approx(result["valid_area_m2"] / 10_000)
    assert [item["class_value"] for item in result["class_areas"]] == [0, 1]
    assert sum(item["area_m2"] for item in result["class_areas"]) == pytest.approx(result["valid_area_m2"])
    assert sum(item["percent_of_valid"] for item in result["class_areas"]) == pytest.approx(100)


def test_projected_area_respects_pixel_size_and_mask():
    spec = RasterSpec.from_bbox(0, 0, 20, 20, 2, 2, crs_epsg=3857)
    result = raster_area_statistics(np.array([[1, 0], [1, 0]], dtype=np.uint8), spec)
    assert result["valid_area_m2"] == pytest.approx(400)
    assert result["flooded_area_m2"] == pytest.approx(200)
    assert result["flooded_percent_of_valid"] == pytest.approx(50)
    assert [item["area_m2"] for item in result["class_areas"]] == pytest.approx([200, 200])


def test_continuous_scores_are_not_invented_as_classes():
    spec = RasterSpec.from_bbox(0, 0, 20, 20, 2, 2, crs_epsg=3857)
    result = raster_area_statistics(np.array([[0.1, 0.3], [0.5, 0.9]]), spec)
    assert "class_areas" not in result
