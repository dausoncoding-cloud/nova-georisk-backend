from unittest.mock import MagicMock

from app.services.gee import indices


def test_ndvi_uses_normalized_difference_with_correct_bands():
    image = MagicMock()
    result = indices.compute_ndvi(image)
    image.normalizedDifference.assert_called_once_with(["B8", "B4"])
    image.normalizedDifference.return_value.rename.assert_called_once_with("NDVI")
    assert result == image.normalizedDifference.return_value.rename.return_value


def test_ndvi_custom_bands():
    image = MagicMock()
    indices.compute_ndvi(image, nir_band="SR_B5", red_band="SR_B4")
    image.normalizedDifference.assert_called_once_with(["SR_B5", "SR_B4"])


def test_ndwi_uses_green_and_nir():
    image = MagicMock()
    indices.compute_ndwi(image)
    image.normalizedDifference.assert_called_once_with(["B3", "B8"])


def test_mndwi_uses_green_and_swir1():
    image = MagicMock()
    indices.compute_mndwi(image)
    image.normalizedDifference.assert_called_once_with(["B3", "B11"])


def test_ndbi_uses_swir1_and_nir():
    image = MagicMock()
    indices.compute_ndbi(image)
    image.normalizedDifference.assert_called_once_with(["B11", "B8"])


def test_nbr_uses_nir_and_swir2():
    image = MagicMock()
    indices.compute_nbr(image)
    image.normalizedDifference.assert_called_once_with(["B8", "B12"])


def test_ndmi_uses_nir_and_swir1():
    image = MagicMock()
    indices.compute_ndmi(image)
    image.normalizedDifference.assert_called_once_with(["B8", "B11"])


def test_evi_uses_expression_with_correct_formula_and_bands():
    image = MagicMock()
    result = indices.compute_evi(image)

    args, kwargs = image.expression.call_args
    formula = args[0]
    band_dict = args[1]

    assert "NIR" in formula and "RED" in formula and "BLUE" in formula
    assert set(band_dict.keys()) == {"NIR", "RED", "BLUE"}
    image.select.assert_any_call("B8")
    image.select.assert_any_call("B4")
    image.select.assert_any_call("B2")
    image.expression.return_value.rename.assert_called_once_with("EVI")
    assert result == image.expression.return_value.rename.return_value


def test_savi_expression_includes_soil_brightness_l():
    image = MagicMock()
    indices.compute_savi(image, soil_brightness_l=0.25)

    args, _ = image.expression.call_args
    formula, band_dict = args[0], args[1]
    assert "L" in formula
    assert band_dict["L"] == 0.25
    image.expression.return_value.rename.assert_called_once_with("SAVI")


def test_bai_expression_uses_red_and_nir():
    image = MagicMock()
    indices.compute_bai(image)

    args, _ = image.expression.call_args
    band_dict = args[1]
    assert set(band_dict.keys()) == {"RED", "NIR"}
    image.expression.return_value.rename.assert_called_once_with("BAI")


def test_dnbr_subtracts_post_from_pre():
    nbr_pre = MagicMock()
    nbr_post = MagicMock()
    result = indices.compute_dnbr(nbr_pre, nbr_post)

    nbr_pre.subtract.assert_called_once_with(nbr_post)
    nbr_pre.subtract.return_value.rename.assert_called_once_with("dNBR")
    assert result == nbr_pre.subtract.return_value.rename.return_value


def test_lst_from_landsat_applies_usgs_scale_and_offset():
    image = MagicMock()
    thermal_band = image.select.return_value
    kelvin = thermal_band.multiply.return_value.add.return_value

    indices.compute_lst_from_landsat(image)

    image.select.assert_called_once_with("ST_B10")
    thermal_band.multiply.assert_called_once_with(0.00341802)
    thermal_band.multiply.return_value.add.assert_called_once_with(149.0)
    kelvin.subtract.assert_called_once_with(273.15)
    kelvin.subtract.return_value.rename.assert_called_once_with("LST")
