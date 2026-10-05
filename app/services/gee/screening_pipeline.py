"""
Flood Screening Atlas — a generic, per-AOI orchestration built on top
of app.services.gee.{ingestion,preprocessing,indices}. This replaces
ad-hoc standalone scripts that called `ee` directly for one specific
AOI: every function here takes an `ee.Geometry` and date strings, so
it works for *any* project's AOI, not a hardcoded location.

Two categories of layer here:
  - Layers already covered by the tested service modules (true
    colour, NDVI, MNDWI, NDBI, cloud/speckle masking) — reused
    directly, not reimplemented.
  - New GEE-native terrain/hazard layers specific to this screening
    product (slope via ee.Terrain, TPI via focal-mean convolution,
    SAR change severity, a weighted hazard screening index) — new
    functions added here, each small enough to unit-test against a
    mocked `ee` module the same way ingestion.py/indices.py are.

This produces a *screening* product — explicitly not a validated flood
inventory. Every function that contributes to the hazard index says so
in its docstring, and the orchestration's metadata output carries the
same caveat through to the API response.
"""
from __future__ import annotations

import ee

from app.services.gee import indices as indices_service
from app.services.gee import ingestion as ingestion_service
from app.services.gee import preprocessing as preprocessing_service

# SAR change threshold: a drop of 1.5 dB or more in VV backscatter is a
# common open-water screening signal (not proof of flooding on its own).
DEFAULT_SAR_CHANGE_THRESHOLD_DB = -1.5
DEFAULT_SLOPE_THRESHOLD_DEGREES = 15
DEFAULT_PERMANENT_WATER_OCCURRENCE_THRESHOLD = 90

JRC_WATER_OCCURRENCE_ASSET = "JRC/GSW1_4/GlobalSurfaceWater"
HYDROSHEDS_FLOW_ACCUMULATION_ASSET = "WWF/HydroSHEDS/15ACC"


# --- Optical layers (reuse the tested indices/preprocessing services) -------

def build_true_colour_composite(s2_collection: ee.ImageCollection) -> ee.Image:
    """Cloud-masked Sentinel-2 median composite, true-colour bands."""
    masked = s2_collection.map(preprocessing_service.mask_sentinel2_clouds)
    return preprocessing_service.median_composite(masked).select(["B4", "B3", "B2"])


def build_ndvi_layer(s2_collection: ee.ImageCollection) -> ee.Image:
    masked = s2_collection.map(preprocessing_service.mask_sentinel2_clouds)
    composite = preprocessing_service.median_composite(masked)
    return indices_service.compute_ndvi(composite)


def build_mndwi_layer(s2_collection: ee.ImageCollection) -> ee.Image:
    masked = s2_collection.map(preprocessing_service.mask_sentinel2_clouds)
    composite = preprocessing_service.median_composite(masked)
    return indices_service.compute_mndwi(composite)


def build_ndbi_layer(s2_collection: ee.ImageCollection) -> ee.Image:
    masked = s2_collection.map(preprocessing_service.mask_sentinel2_clouds)
    composite = preprocessing_service.median_composite(masked)
    return indices_service.compute_ndbi(composite)


# --- SAR change detection ----------------------------------------------------

def build_sar_vv_composite(s1_collection: ee.ImageCollection) -> ee.Image:
    """Median VV composite from a Sentinel-1 collection (already filtered by ingestion.get_sentinel1_collection)."""
    return s1_collection.select("VV").median()


def compute_sar_change(vv_before: ee.Image, vv_after: ee.Image) -> ee.Image:
    """Change (dB) = after - before. Negative = backscatter drop (open-water screening signal)."""
    return vv_after.subtract(vv_before).rename("sar_change_db")


def classify_sar_change_severity(change_db: ee.Image) -> ee.Image:
    """
    4-class severity screen: minimal (> -0.5 dB), low (-0.5 to -1.5),
    moderate (-1.5 to -3), high (<= -3 dB drop).
    """
    return (
        ee.Image(0)
        .where(change_db.lte(-0.5), 1)
        .where(change_db.lte(-1.5), 2)
        .where(change_db.lte(-3.0), 3)
        .rename("sar_change_severity")
    )


def screen_binary_flood_extent(
    change_db: ee.Image,
    slope_degrees: ee.Image,
    water_occurrence_pct: ee.Image,
    change_threshold_db: float = DEFAULT_SAR_CHANGE_THRESHOLD_DB,
    slope_threshold_degrees: float = DEFAULT_SLOPE_THRESHOLD_DEGREES,
    water_occurrence_threshold_pct: float = DEFAULT_PERMANENT_WATER_OCCURRENCE_THRESHOLD,
) -> ee.Image:
    """
    Screening binary flood mask: SAR change beyond threshold, AND flat
    enough to plausibly pond, AND not already permanent open water.
    Explicitly a screening indicator (per every calling script's own
    metadata caveat), not a validated flood-extent product.
    """
    candidate = change_db.lte(change_threshold_db)
    flat_enough = slope_degrees.lt(slope_threshold_degrees)
    not_permanent_water = water_occurrence_pct.lt(water_occurrence_threshold_pct)
    return candidate.And(flat_enough).And(not_permanent_water).rename("binary_flood_extent")


# --- Terrain (GEE-native — different execution model from the local-numpy
# hydrology.watershed module, which operates on already-downloaded rasters) --

def compute_slope_degrees(dem: ee.Image) -> ee.Image:
    """Slope in degrees via Earth Engine's built-in terrain algorithm."""
    return ee.Terrain.slope(dem)


def compute_tpi(dem: ee.Image, radius_meters: float = 30) -> ee.Image:
    """
    Topographic Position Index = elevation - local mean elevation.
    Positive = ridge/high relative to surroundings, negative = valley/
    depression — depressions are where screened water would pond.
    """
    kernel = ee.Kernel.circle(radius=radius_meters, units="meters")
    local_mean = dem.reduceNeighborhood(reducer=ee.Reducer.mean(), kernel=kernel)
    return dem.subtract(local_mean).rename("tpi")


def get_water_occurrence(aoi: ee.Geometry) -> ee.Image:
    """JRC Global Surface Water occurrence (%) — used both for TWI-adjacent context and the binary screen."""
    return ee.Image(JRC_WATER_OCCURRENCE_ASSET).select("occurrence").clip(aoi).unmask(0)


def compute_distance_to_water_m(water_occurrence_pct: ee.Image, threshold_pct: float = 50) -> ee.Image:
    """Euclidean distance (m) to the nearest pixel exceeding the water-occurrence threshold."""
    water_mask = water_occurrence_pct.gte(threshold_pct)
    return water_mask.fastDistanceTransform().sqrt().multiply(ee.Image.pixelArea().sqrt()).rename("distance_to_water_m")


def compute_twi(dem: ee.Image, aoi: ee.Geometry) -> ee.Image:
    """
    TWI = ln(flow_accumulation_area / tan(slope)), using the precomputed
    HydroSHEDS flow-accumulation grid (continental-scale flow routing
    isn't practical as a server-side GEE expression the way the local
    D8 algorithm in hydrology.watershed is for an already-downloaded,
    AOI-sized raster — this is the standard GEE-native approach instead).
    """
    flow_accumulation = ee.Image(HYDROSHEDS_FLOW_ACCUMULATION_ASSET).clip(aoi)
    slope_rad = compute_slope_degrees(dem).multiply(3.14159265 / 180).max(0.001)  # avoid tan(0)
    return flow_accumulation.divide(slope_rad.tan()).log().rename("twi")


# --- Composite hazard screening index ----------------------------------------

def compute_hazard_screening_index(
    sar_candidate: ee.Image,
    elevation: ee.Image,
    slope_degrees: ee.Image,
    twi: ee.Image,
    distance_to_water_m: ee.Image,
    rainfall_mm: ee.Image,
    ndvi: ee.Image,
) -> ee.Image:
    """
    Weighted screening hazard index (0-1): 0.30 SAR candidate +
    0.15 inverse elevation + 0.10 inverse slope + 0.15 TWI +
    0.15 inverse distance-to-water + 0.10 rainfall + 0.05 inverse NDVI.
    Every input is min-max normalized to [0,1] over the AOI first;
    weights sum to 1.0. This is a fixed-weight screening formula (not
    the FIRRIS module's entropy-weighted H) — appropriate for a quick
    multi-factor screen, not a substitute for the full FIRRIS pipeline.
    """

    def _normalize(image: ee.Image, aoi_geom: ee.Geometry, band_name: str) -> ee.Image:
        stats = image.reduceRegion(
            reducer=ee.Reducer.minMax(), geometry=aoi_geom, scale=90, maxPixels=1e9, bestEffort=True
        )
        band_min = ee.Number(stats.get(f"{band_name}_min"))
        band_max = ee.Number(stats.get(f"{band_name}_max"))
        span = band_max.subtract(band_min).max(1e-9)
        return image.subtract(band_min).divide(span)

    aoi_geom = elevation.geometry()
    sar_n = _normalize(sar_candidate.toFloat(), aoi_geom, "binary_flood_extent")
    elev_n = _normalize(elevation, aoi_geom, "elevation")
    slope_n = _normalize(slope_degrees, aoi_geom, "slope")
    twi_n = _normalize(twi, aoi_geom, "twi")
    dist_n = _normalize(distance_to_water_m, aoi_geom, "distance_to_water_m")
    rain_n = _normalize(rainfall_mm, aoi_geom, "precipitation")
    ndvi_n = _normalize(ndvi, aoi_geom, "NDVI")

    hazard = (
        sar_n.multiply(0.30)
        .add(elev_n.multiply(-1).add(1).multiply(0.15))  # inverse elevation
        .add(slope_n.multiply(-1).add(1).multiply(0.10))  # inverse slope
        .add(twi_n.multiply(0.15))
        .add(dist_n.multiply(-1).add(1).multiply(0.15))  # inverse distance to water
        .add(rain_n.multiply(0.10))
        .add(ndvi_n.multiply(-1).add(1).multiply(0.05))  # inverse NDVI
    )
    return hazard.rename("hazard_screening_index")


def classify_hazard_five_classes(hazard_index: ee.Image) -> ee.Image:
    """0-1 hazard index -> 5 classes (1=Very Low ... 5=Extreme), equal-interval bands."""
    return (
        ee.Image(1)
        .where(hazard_index.gt(0.20), 2)
        .where(hazard_index.gt(0.40), 3)
        .where(hazard_index.gt(0.60), 4)
        .where(hazard_index.gt(0.80), 5)
        .rename("hazard_class")
    )
