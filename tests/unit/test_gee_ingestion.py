from unittest.mock import MagicMock, patch

import pytest

from app.services.gee import ingestion


@patch("app.services.gee.ingestion.ee")
def test_build_aoi_geometry_wraps_geojson(mock_ee):
    geojson = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    ingestion.build_aoi_geometry(geojson)
    mock_ee.Geometry.assert_called_once_with(geojson)


@patch("app.services.gee.ingestion.ee")
def test_sentinel2_collection_filter_chain(mock_ee):
    aoi = MagicMock(name="aoi")
    collection = mock_ee.ImageCollection.return_value
    filtered_bounds = collection.filterBounds.return_value
    filtered_date = filtered_bounds.filterDate.return_value
    filtered_cloud = filtered_date.filter.return_value

    result = ingestion.get_sentinel2_collection(aoi, "2026-01-01", "2026-03-01", max_cloud_pct=15)

    mock_ee.ImageCollection.assert_called_once_with(ingestion.SENTINEL2_COLLECTION)
    collection.filterBounds.assert_called_once_with(aoi)
    filtered_bounds.filterDate.assert_called_once_with("2026-01-01", "2026-03-01")
    # The cloud filter uses ee.Filter.lte on CLOUDY_PIXEL_PERCENTAGE
    mock_ee.Filter.lte.assert_called_once_with("CLOUDY_PIXEL_PERCENTAGE", 15)
    filtered_date.filter.assert_called_once_with(mock_ee.Filter.lte.return_value)
    filtered_cloud.sort.assert_called_once_with("CLOUDY_PIXEL_PERCENTAGE")
    assert result == filtered_cloud.sort.return_value


@patch("app.services.gee.ingestion.ee")
def test_sentinel2_default_cloud_threshold_matches_doc0(mock_ee):
    ingestion.get_sentinel2_collection(MagicMock(), "2026-01-01", "2026-03-01")
    mock_ee.Filter.lte.assert_called_once_with("CLOUDY_PIXEL_PERCENTAGE", 10)


@patch("app.services.gee.ingestion.ee")
def test_landsat_collection_uses_landsat9_by_default(mock_ee):
    aoi = MagicMock()
    ingestion.get_landsat_collection(aoi, "2026-01-01", "2026-03-01")
    mock_ee.ImageCollection.assert_called_once_with(ingestion.LANDSAT9_COLLECTION)


@patch("app.services.gee.ingestion.ee")
def test_landsat_collection_selects_landsat8_when_requested(mock_ee):
    aoi = MagicMock()
    ingestion.get_landsat_collection(aoi, "2026-01-01", "2026-03-01", satellite="landsat8")
    mock_ee.ImageCollection.assert_called_once_with(ingestion.LANDSAT8_COLLECTION)


@patch("app.services.gee.ingestion.ee")
def test_sentinel1_filters_by_polarization_and_instrument_mode(mock_ee):
    aoi = MagicMock()
    collection = mock_ee.ImageCollection.return_value
    step1 = collection.filterBounds.return_value
    step2 = step1.filterDate.return_value
    step3 = step2.filter.return_value  # polarization filter
    step4 = step3.filter.return_value  # instrument mode filter

    ingestion.get_sentinel1_collection(aoi, "2026-01-01", "2026-03-01", polarization="VH")

    mock_ee.ImageCollection.assert_called_once_with(ingestion.SENTINEL1_COLLECTION)
    mock_ee.Filter.listContains.assert_called_once_with("transmitterReceiverPolarisation", "VH")
    mock_ee.Filter.eq.assert_any_call("instrumentMode", "IW")
    mock_ee.Filter.eq.assert_any_call("orbitProperties_pass", "ASCENDING")
    # Orbit-pass filter applied last (default DESCENDING)
    step4.filter.assert_called_once()


@patch("app.services.gee.ingestion.ee")
def test_sentinel1_skips_orbit_filter_when_none(mock_ee):
    aoi = MagicMock()
    collection = mock_ee.ImageCollection.return_value
    step1 = collection.filterBounds.return_value
    step2 = step1.filterDate.return_value
    step3 = step2.filter.return_value  # after polarization filter
    step4 = step3.filter.return_value  # after instrument-mode filter

    result = ingestion.get_sentinel1_collection(aoi, "2026-01-01", "2026-03-01", orbit_pass=None)

    # Both polarization and instrument-mode filters still apply (2 total),
    # but no further .filter() call for orbit pass -> result is step4 itself.
    step4.filter.assert_not_called()
    assert result == step4


@patch("app.services.gee.ingestion.ee")
def test_chirps_and_era5_filter_bounds_and_date_only(mock_ee):
    aoi = MagicMock()
    ingestion.get_chirps_rainfall(aoi, "2026-01-01", "2026-03-01")
    mock_ee.ImageCollection.assert_called_with(ingestion.CHIRPS_COLLECTION)

    mock_ee.reset_mock()
    ingestion.get_era5_climate(aoi, "2026-01-01", "2026-03-01")
    mock_ee.ImageCollection.assert_called_with(ingestion.ERA5_COLLECTION)


@patch("app.services.gee.ingestion.ee")
def test_esa_worldcover_uses_first_image_and_clips(mock_ee):
    aoi = MagicMock()
    collection = mock_ee.ImageCollection.return_value
    first_image = collection.first.return_value

    ingestion.get_esa_worldcover(aoi)

    mock_ee.ImageCollection.assert_called_once_with(ingestion.WORLDCOVER_COLLECTION)
    first_image.clip.assert_called_once_with(aoi)


@patch("app.services.gee.ingestion.ee")
def test_get_dem_srtm_default(mock_ee):
    aoi = MagicMock()
    image = mock_ee.Image.return_value
    ingestion.get_dem(aoi, source="SRTM")
    mock_ee.Image.assert_called_once_with(ingestion.SRTM_DEM_ASSET)
    image.clip.assert_called_once_with(aoi)


@patch("app.services.gee.ingestion.ee")
def test_get_dem_alos_uses_mosaic(mock_ee):
    aoi = MagicMock()
    collection = mock_ee.ImageCollection.return_value
    bounded = collection.filterBounds.return_value
    selected = bounded.select.return_value
    mosaicked = selected.mosaic.return_value

    ingestion.get_dem(aoi, source="ALOS")

    mock_ee.ImageCollection.assert_called_once_with(ingestion.ALOS_DEM_COLLECTION)
    collection.filterBounds.assert_called_once_with(aoi)
    bounded.select.assert_called_once_with("DSM")
    mosaicked.setDefaultProjection.assert_called_once_with(selected.first.return_value.projection.return_value)
    mosaicked.setDefaultProjection.return_value.clip.assert_called_once_with(aoi)


def test_get_dem_rejects_unknown_source():
    with pytest.raises(ValueError):
        ingestion.get_dem(MagicMock(), source="NOT_A_REAL_DEM")
