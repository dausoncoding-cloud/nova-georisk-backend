import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from app.services.maps.export import (
    RasterSpec,
    colorize_classified_raster,
    export_flood_extent_geojson,
    read_geotiff,
    write_geotiff,
    write_cog,
    write_png,
)


def test_raster_spec_from_bounds_places_top_left_correctly():
    spec = RasterSpec.from_bounds(west=30.0, north=-5.0, pixel_size=0.01, crs_epsg=4326)
    x, y = spec.transform @ (0, 0)
    assert x == pytest.approx(30.0)
    assert y == pytest.approx(-5.0)
    # One pixel down and right should move south and east
    x1, y1 = spec.transform @ (1, 1)
    assert x1 > x
    assert y1 < y


def test_geotiff_round_trip_preserves_data():
    array = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    spec = RasterSpec.from_bounds(west=39.2, north=-6.8, pixel_size=0.001)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(Path(tmpdir) / "test.tif")
        write_geotiff(path, array, spec)
        read_array, read_spec = read_geotiff(path)

        np.testing.assert_allclose(read_array, array)
        assert read_spec.crs_epsg == 4326


def test_geotiff_rejects_non_2d_array():
    array = np.zeros((2, 2, 2))
    spec = RasterSpec.from_bounds(west=0, north=0, pixel_size=1)
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(ValueError):
            write_geotiff(str(Path(tmpdir) / "bad.tif"), array, spec)


def test_cog_round_trip_is_tiled():
    import rasterio

    array = np.arange(1024, dtype=np.float32).reshape(32, 32)
    spec = RasterSpec.from_bounds(west=39.2, north=-6.8, pixel_size=0.001)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(Path(tmpdir) / "test.cog.tif")
        write_cog(path, array, spec, nodata=-9999)
        with rasterio.open(path) as source:
            assert source.is_tiled
            np.testing.assert_allclose(source.read(1), array)


def test_colorize_classified_raster_applies_correct_colors():
    labels = np.array([["Very Low", "High"], ["High", "Very Low"]])
    color_map = {"Very Low": "#006400", "High": "#FFA500"}

    image = colorize_classified_raster(labels, color_map)
    pixels = np.array(image)

    assert tuple(pixels[0, 0]) == (0x00, 0x64, 0x00)  # Very Low -> dark green
    assert tuple(pixels[0, 1]) == (0xFF, 0xA5, 0x00)  # High -> orange


def test_write_png_creates_readable_file():
    labels = np.array([["Very Low", "High"]])
    color_map = {"Very Low": "#006400", "High": "#FFA500"}

    with tempfile.TemporaryDirectory() as tmpdir:
        path = str(Path(tmpdir) / "test.png")
        write_png(path, labels, color_map)
        assert Path(path).exists()
        assert Path(path).stat().st_size > 0


def test_export_flood_extent_geojson_structure():
    mask = np.array([[True, False], [False, True]])
    spec = RasterSpec.from_bounds(west=39.0, north=-6.0, pixel_size=0.01)

    geojson = export_flood_extent_geojson(mask, spec)
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 2  # two True cells
    for feature in geojson["features"]:
        assert feature["geometry"]["type"] == "Polygon"
        assert feature["properties"]["class"] == "flooded"

    # Should be valid, serializable JSON
    json.dumps(geojson)


def test_extent_vector_merges_adjacent_pixels_and_reprojects_to_wgs84():
    mask = np.array([[True, True], [False, False]])
    spec = RasterSpec.from_bbox(4_000_000, -300_000, 4_001_000, -299_000, 2, 2, crs_epsg=3857)
    geojson = export_flood_extent_geojson(mask, spec)
    assert len(geojson["features"]) == 1
    assert "crs" not in geojson
    longitude = geojson["features"][0]["geometry"]["coordinates"][0][0][0]
    assert 30 < longitude < 40


def test_export_flood_extent_geojson_empty_mask():
    mask = np.zeros((3, 3), dtype=bool)
    spec = RasterSpec.from_bounds(west=0, north=0, pixel_size=1)
    geojson = export_flood_extent_geojson(mask, spec)
    assert geojson["features"] == []
