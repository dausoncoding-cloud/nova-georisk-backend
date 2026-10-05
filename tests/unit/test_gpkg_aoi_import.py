import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from app.api.v1.endpoints.aoi import _uploaded_geopackage_geometry


def test_geopackage_polygon_is_normalized_to_wgs84(tmp_path):
    path = tmp_path / "boundary.gpkg"
    frame = gpd.GeoDataFrame(
        {"name": ["floodplain"]},
        geometry=[Polygon([(36, -2), (37, -2), (37, -1), (36, -1), (36, -2)])],
        crs="EPSG:4326",
    ).to_crs(3857)
    frame.to_file(path, driver="GPKG")
    geometry = _uploaded_geopackage_geometry(path.read_bytes())
    assert geometry["type"] == "Polygon"
    assert geometry["coordinates"][0][0][0] == pytest.approx(36)
    assert geometry["coordinates"][0][0][1] == pytest.approx(-2)


def test_geopackage_rejects_invalid_file():
    with pytest.raises(ValueError, match="could not be read"):
        _uploaded_geopackage_geometry(b"not a GeoPackage")


def test_geopackage_requires_explicit_vetted_layer_when_multiple_are_present(tmp_path):
    path = tmp_path / "multi.gpkg"
    first = gpd.GeoDataFrame(
        {"name": ["first"]}, geometry=[Polygon([(36, -2), (37, -2), (37, -1), (36, -2)])],
        crs="EPSG:4326",
    )
    second = gpd.GeoDataFrame(
        {"name": ["second"]}, geometry=[Polygon([(38, -2), (39, -2), (39, -1), (38, -2)])],
        crs="EPSG:4326",
    )
    first.to_file(path, layer="first", driver="GPKG")
    second.to_file(path, layer="second", driver="GPKG", mode="a")
    data = path.read_bytes()
    with pytest.raises(ValueError, match="Select one"):
        _uploaded_geopackage_geometry(data)
    with pytest.raises(ValueError, match="not an available polygon"):
        _uploaded_geopackage_geometry(data, "unknown")
    geometry = _uploaded_geopackage_geometry(data, "second")
    assert geometry["coordinates"][0][0] == [38, -2] or geometry["coordinates"][0][0] == (38, -2)
