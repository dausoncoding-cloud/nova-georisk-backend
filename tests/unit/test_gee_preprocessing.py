from unittest.mock import MagicMock

from app.services.gee import preprocessing


def test_mask_sentinel2_clouds_builds_correct_scl_mask():
    image = MagicMock()
    scl = image.select.return_value
    result = preprocessing.mask_sentinel2_clouds(image)

    image.select.assert_called_once_with("SCL")
    for invalid_class in (0, 1, 3, 8, 9, 10, 11):
        scl.neq.assert_any_call(invalid_class)
    assert scl.neq.call_count == 7
    image.updateMask.assert_called_once()
    assert result == image.updateMask.return_value


def test_mask_landsat_clouds_uses_correct_bit_flags():
    image = MagicMock()
    qa = image.select.return_value

    preprocessing.mask_landsat_clouds(image)

    image.select.assert_called_once_with("QA_PIXEL")
    for mask in (1, 2, 4, 8, 16, 32):
        qa.bitwiseAnd.assert_any_call(mask)
    assert qa.bitwiseAnd.call_count == 6
    image.updateMask.assert_called_once()


def test_apply_speckle_filter_uses_focal_median_with_given_radius():
    image = MagicMock()
    preprocessing.apply_speckle_filter(image, radius=30)
    image.focal_median.assert_called_once_with(30, "circle", "meters")


def test_apply_speckle_filter_default_radius():
    image = MagicMock()
    preprocessing.apply_speckle_filter(image)
    image.focal_median.assert_called_once_with(50, "circle", "meters")


def test_clip_to_aoi():
    image = MagicMock()
    aoi = MagicMock()
    result = preprocessing.clip_to_aoi(image, aoi)
    image.clip.assert_called_once_with(aoi)
    assert result == image.clip.return_value


def test_mosaic_collection():
    collection = MagicMock()
    result = preprocessing.mosaic_collection(collection)
    collection.mosaic.assert_called_once()
    assert result == collection.mosaic.return_value


def test_median_composite():
    collection = MagicMock()
    result = preprocessing.median_composite(collection)
    collection.median.assert_called_once()
    assert result == collection.median.return_value


def test_select_bands():
    image = MagicMock()
    result = preprocessing.select_bands(image, ["B4", "B8"])
    image.select.assert_called_once_with(["B4", "B8"])
    assert result == image.select.return_value
