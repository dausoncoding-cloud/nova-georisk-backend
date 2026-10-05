from unittest.mock import MagicMock, patch

from app.services.gee import screening_pipeline as pipeline


@patch("app.services.gee.screening_pipeline.preprocessing_service")
def test_build_true_colour_composite_masks_and_selects_rgb(mock_preprocessing):
    collection = MagicMock()
    masked = collection.map.return_value
    composite = mock_preprocessing.median_composite.return_value

    result = pipeline.build_true_colour_composite(collection)

    collection.map.assert_called_once_with(mock_preprocessing.mask_sentinel2_clouds)
    mock_preprocessing.median_composite.assert_called_once_with(masked)
    composite.select.assert_called_once_with(["B4", "B3", "B2"])
    assert result == composite.select.return_value


@patch("app.services.gee.screening_pipeline.indices_service")
@patch("app.services.gee.screening_pipeline.preprocessing_service")
def test_build_ndvi_layer_uses_indices_service(mock_preprocessing, mock_indices):
    collection = MagicMock()
    pipeline.build_ndvi_layer(collection)
    composite = mock_preprocessing.median_composite.return_value
    mock_indices.compute_ndvi.assert_called_once_with(composite)


@patch("app.services.gee.screening_pipeline.indices_service")
@patch("app.services.gee.screening_pipeline.preprocessing_service")
def test_build_mndwi_layer_uses_indices_service(mock_preprocessing, mock_indices):
    collection = MagicMock()
    pipeline.build_mndwi_layer(collection)
    composite = mock_preprocessing.median_composite.return_value
    mock_indices.compute_mndwi.assert_called_once_with(composite)


def test_build_sar_vv_composite_selects_vv_and_medians():
    collection = MagicMock()
    result = pipeline.build_sar_vv_composite(collection)
    collection.select.assert_called_once_with("VV")
    collection.select.return_value.median.assert_called_once()
    assert result == collection.select.return_value.median.return_value


def test_compute_sar_change_is_after_minus_before():
    before = MagicMock()
    after = MagicMock()
    result = pipeline.compute_sar_change(before, after)
    after.subtract.assert_called_once_with(before)
    after.subtract.return_value.rename.assert_called_once_with("sar_change_db")
    assert result == after.subtract.return_value.rename.return_value


def test_classify_sar_change_severity_thresholds():
    change = MagicMock()
    with patch("app.services.gee.screening_pipeline.ee") as mock_ee:
        base = mock_ee.Image.return_value
        pipeline.classify_sar_change_severity(change)
        mock_ee.Image.assert_called_once_with(0)
        change.lte.assert_any_call(-0.5)
        change.lte.assert_any_call(-1.5)
        change.lte.assert_any_call(-3.0)
        # Each .where() chains off the previous call's return value (proper GEE chaining),
        # so the base mock's .where is only called once directly; the chain is 3 deep.
        base.where.assert_called_once()
        base.where.return_value.where.assert_called_once()
        base.where.return_value.where.return_value.where.assert_called_once()
        base.where.return_value.where.return_value.where.return_value.rename.assert_called_once_with(
            "sar_change_severity"
        )


def test_screen_binary_flood_extent_ands_three_conditions():
    change = MagicMock()
    slope = MagicMock()
    water = MagicMock()

    candidate = change.lte.return_value
    flat = slope.lt.return_value
    not_water = water.lt.return_value

    result = pipeline.screen_binary_flood_extent(change, slope, water)

    change.lte.assert_called_once_with(pipeline.DEFAULT_SAR_CHANGE_THRESHOLD_DB)
    slope.lt.assert_called_once_with(pipeline.DEFAULT_SLOPE_THRESHOLD_DEGREES)
    water.lt.assert_called_once_with(pipeline.DEFAULT_PERMANENT_WATER_OCCURRENCE_THRESHOLD)
    candidate.And.assert_called_once_with(flat)
    candidate.And.return_value.And.assert_called_once_with(not_water)
    candidate.And.return_value.And.return_value.rename.assert_called_once_with("binary_flood_extent")
    assert result == candidate.And.return_value.And.return_value.rename.return_value


def test_screen_binary_flood_extent_custom_thresholds():
    change, slope, water = MagicMock(), MagicMock(), MagicMock()
    pipeline.screen_binary_flood_extent(
        change, slope, water, change_threshold_db=-2.0, slope_threshold_degrees=20, water_occurrence_threshold_pct=80
    )
    change.lte.assert_called_once_with(-2.0)
    slope.lt.assert_called_once_with(20)
    water.lt.assert_called_once_with(80)


@patch("app.services.gee.screening_pipeline.ee")
def test_compute_slope_degrees_uses_ee_terrain(mock_ee):
    dem = MagicMock()
    result = pipeline.compute_slope_degrees(dem)
    mock_ee.Terrain.slope.assert_called_once_with(dem)
    assert result == mock_ee.Terrain.slope.return_value


@patch("app.services.gee.screening_pipeline.ee")
def test_compute_tpi_uses_focal_mean_convolution(mock_ee):
    dem = MagicMock()
    kernel = mock_ee.Kernel.circle.return_value
    local_mean = dem.reduceNeighborhood.return_value

    result = pipeline.compute_tpi(dem, radius_meters=500)

    mock_ee.Kernel.circle.assert_called_once_with(radius=500, units="meters")
    dem.reduceNeighborhood.assert_called_once_with(reducer=mock_ee.Reducer.mean.return_value, kernel=kernel)
    dem.subtract.assert_called_once_with(local_mean)
    dem.subtract.return_value.rename.assert_called_once_with("tpi")
    assert result == dem.subtract.return_value.rename.return_value


@patch("app.services.gee.screening_pipeline.ee")
def test_get_water_occurrence_clips_and_unmasks(mock_ee):
    aoi = MagicMock()
    image = mock_ee.Image.return_value
    selected = image.select.return_value
    clipped = selected.clip.return_value

    pipeline.get_water_occurrence(aoi)

    mock_ee.Image.assert_called_once_with(pipeline.JRC_WATER_OCCURRENCE_ASSET)
    image.select.assert_called_once_with("occurrence")
    selected.clip.assert_called_once_with(aoi)
    clipped.unmask.assert_called_once_with(0)


@patch("app.services.gee.screening_pipeline.ee")
def test_compute_distance_to_water_m_thresholds_and_transforms(mock_ee):
    water_occurrence = MagicMock()
    mask = water_occurrence.gte.return_value

    pipeline.compute_distance_to_water_m(water_occurrence, threshold_pct=75)

    water_occurrence.gte.assert_called_once_with(75)
    mask.fastDistanceTransform.assert_called_once()
    mock_ee.Image.pixelArea.assert_called_once()


@patch("app.services.gee.screening_pipeline.ee")
def test_compute_twi_uses_hydrosheds_flow_accumulation(mock_ee):
    dem = MagicMock()
    aoi = MagicMock()

    with patch.object(pipeline, "compute_slope_degrees") as mock_slope:
        pipeline.compute_twi(dem, aoi)
        mock_ee.Image.assert_called_once_with(pipeline.HYDROSHEDS_FLOW_ACCUMULATION_ASSET)
        mock_ee.Image.return_value.clip.assert_called_once_with(aoi)
        mock_slope.assert_called_once_with(dem)


def test_classify_hazard_five_classes_thresholds():
    hazard = MagicMock()
    with patch("app.services.gee.screening_pipeline.ee") as mock_ee:
        base = mock_ee.Image.return_value
        pipeline.classify_hazard_five_classes(hazard)
        mock_ee.Image.assert_called_once_with(1)
        hazard.gt.assert_any_call(0.20)
        hazard.gt.assert_any_call(0.40)
        hazard.gt.assert_any_call(0.60)
        hazard.gt.assert_any_call(0.80)
        # 4-deep chain of .where(), same chaining pattern as the severity classifier above.
        chain = base.where.return_value.where.return_value.where.return_value.where.return_value
        base.where.assert_called_once()
        chain.rename.assert_called_once_with("hazard_class")
