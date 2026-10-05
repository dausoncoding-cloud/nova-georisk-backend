"""
Spectral Index Derivation — Doc 0 step 11: NDVI, EVI, NDWI, MNDWI,
NDBI, SAVI, BAI, NBR, dNBR, NDMI, LST. Formulas use standard Sentinel-2
Surface Reflectance band names (B2 Blue, B3 Green, B4 Red, B8 NIR,
B11 SWIR1, B12 SWIR2) unless noted; each function returns a single
renamed band so results chain cleanly with `.addBands()`.
"""
from __future__ import annotations

import ee


def compute_ndvi(image: ee.Image, nir_band: str = "B8", red_band: str = "B4") -> ee.Image:
    """NDVI = (NIR - Red) / (NIR + Red)."""
    return image.normalizedDifference([nir_band, red_band]).rename("NDVI")


def compute_evi(
    image: ee.Image, nir_band: str = "B8", red_band: str = "B4", blue_band: str = "B2"
) -> ee.Image:
    """EVI = 2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1)."""
    return image.expression(
        "2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))",
        {
            "NIR": image.select(nir_band),
            "RED": image.select(red_band),
            "BLUE": image.select(blue_band),
        },
    ).rename("EVI")


def compute_ndwi(image: ee.Image, green_band: str = "B3", nir_band: str = "B8") -> ee.Image:
    """NDWI (McFeeters) = (Green - NIR) / (Green + NIR) — open water."""
    return image.normalizedDifference([green_band, nir_band]).rename("NDWI")


def compute_mndwi(image: ee.Image, green_band: str = "B3", swir1_band: str = "B11") -> ee.Image:
    """MNDWI = (Green - SWIR1) / (Green + SWIR1) — better than NDWI for built-up/turbid water."""
    return image.normalizedDifference([green_band, swir1_band]).rename("MNDWI")


def compute_ndbi(image: ee.Image, swir1_band: str = "B11", nir_band: str = "B8") -> ee.Image:
    """NDBI = (SWIR1 - NIR) / (SWIR1 + NIR) — built-up index."""
    return image.normalizedDifference([swir1_band, nir_band]).rename("NDBI")


def compute_savi(
    image: ee.Image, nir_band: str = "B8", red_band: str = "B4", soil_brightness_l: float = 0.5
) -> ee.Image:
    """SAVI = ((NIR - Red) / (NIR + Red + L)) * (1 + L), L=0.5 by default (moderate vegetation cover)."""
    return image.expression(
        "((NIR - RED) / (NIR + RED + L)) * (1 + L)",
        {"NIR": image.select(nir_band), "RED": image.select(red_band), "L": soil_brightness_l},
    ).rename("SAVI")


def compute_bai(image: ee.Image, red_band: str = "B4", nir_band: str = "B8") -> ee.Image:
    """BAI (Burn Area Index) = 1 / ((0.1 - Red)^2 + (0.06 - NIR)^2)."""
    return image.expression(
        "1.0 / ((0.1 - RED) ** 2 + (0.06 - NIR) ** 2)",
        {"RED": image.select(red_band), "NIR": image.select(nir_band)},
    ).rename("BAI")


def compute_nbr(image: ee.Image, nir_band: str = "B8", swir2_band: str = "B12") -> ee.Image:
    """NBR = (NIR - SWIR2) / (NIR + SWIR2) — Normalized Burn Ratio."""
    return image.normalizedDifference([nir_band, swir2_band]).rename("NBR")


def compute_dnbr(nbr_pre: ee.Image, nbr_post: ee.Image) -> ee.Image:
    """dNBR = NBR_pre-fire - NBR_post-fire — burn severity (positive = more severe burn)."""
    return nbr_pre.subtract(nbr_post).rename("dNBR")


def compute_ndmi(image: ee.Image, nir_band: str = "B8", swir1_band: str = "B11") -> ee.Image:
    """NDMI = (NIR - SWIR1) / (NIR + SWIR1) — vegetation moisture content."""
    return image.normalizedDifference([nir_band, swir1_band]).rename("NDMI")


def compute_lst_from_landsat(image: ee.Image, thermal_band: str = "ST_B10") -> ee.Image:
    """
    Land Surface Temperature (°C) from a Landsat Collection 2 Level-2
    thermal band. USGS's documented scale/offset converts the raw DN
    to Kelvin (ST_B10 * 0.00341802 + 149.0); subtracting 273.15 gives °C.
    """
    kelvin = image.select(thermal_band).multiply(0.00341802).add(149.0)
    return kelvin.subtract(273.15).rename("LST")
