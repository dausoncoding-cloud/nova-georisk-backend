"""
GEE Data Ingestion — Doc 0 "Universal GEE Integration": Sentinel-1 SAR,
Sentinel-2 Optical, Landsat 8/9, DEM, CHIRPS, ERA5, ESA WorldCover.

Every function here builds and returns an `ee.ImageCollection` (or
`ee.Image` for single-asset sources like DEM/WorldCover) filtered to
the AOI and date range, with the collection-level cloud-cover filter
Doc 0 specifies. Nothing here calls `.getInfo()` or otherwise forces
a network round-trip — that only happens when the caller actually
pulls pixels (export/sampling), which needs a live, authenticated GEE
session. The filtering/selection *logic* itself has no such
dependency and is unit-tested against a mocked `ee` module.
"""
from __future__ import annotations

import ee

# Doc 0 §9 "Recommended threshold by application"
CLOUD_THRESHOLD_LAND_COVER = 10
CLOUD_THRESHOLD_FLOOD_SAR = 20

SENTINEL2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
SENTINEL1_COLLECTION = "COPERNICUS/S1_GRD"
LANDSAT8_COLLECTION = "LANDSAT/LC08/C02/T1_L2"
LANDSAT9_COLLECTION = "LANDSAT/LC09/C02/T1_L2"
CHIRPS_COLLECTION = "UCSB-CHG/CHIRPS/DAILY"
ERA5_COLLECTION = "ECMWF/ERA5_LAND/DAILY_AGGR"
WORLDCOVER_COLLECTION = "ESA/WorldCover/v200"
SRTM_DEM_ASSET = "USGS/SRTMGL1_003"
ALOS_DEM_COLLECTION = "JAXA/ALOS/AW3D30/V3_2"


def build_aoi_geometry(geojson_geometry: dict) -> ee.Geometry:
    """Convert a GeoJSON Polygon/MultiPolygon dict into an ee.Geometry."""
    return ee.Geometry(geojson_geometry)


def get_sentinel2_collection(
    aoi: ee.Geometry,
    start_date: str,
    end_date: str,
    max_cloud_pct: float = CLOUD_THRESHOLD_LAND_COVER,
) -> ee.ImageCollection:
    """Sentinel-2 Surface Reflectance, filtered by AOI/date/cloud cover — Doc 0 steps 7-8."""
    return (
        ee.ImageCollection(SENTINEL2_COLLECTION)
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", max_cloud_pct))
        .sort("CLOUDY_PIXEL_PERCENTAGE")
    )


def get_landsat_collection(
    aoi: ee.Geometry,
    start_date: str,
    end_date: str,
    satellite: str = "landsat9",
    max_cloud_pct: float = CLOUD_THRESHOLD_LAND_COVER,
) -> ee.ImageCollection:
    """Landsat 8 or 9 Collection 2 Level-2 Surface Reflectance."""
    asset = LANDSAT9_COLLECTION if satellite == "landsat9" else LANDSAT8_COLLECTION
    return (
        ee.ImageCollection(asset)
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lte("CLOUD_COVER", max_cloud_pct))
        .sort("CLOUD_COVER")
    )


def get_sentinel1_collection(
    aoi: ee.Geometry,
    start_date: str,
    end_date: str,
    polarization: str = "VV",
    orbit_pass: str | None = "ASCENDING",
) -> ee.ImageCollection:
    """
    Sentinel-1 SAR GRD — Doc 0's SAR path for flood mapping, used
    specifically *to avoid* the cloud-cover problem optical imagery has
    ('Flood Mapping: ≤20% or use SAR imagery to avoid cloud issues').
    No cloud filter applies here; SAR penetrates cloud cover.
    """
    collection = (
        ee.ImageCollection(SENTINEL1_COLLECTION)
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", polarization))
        .filter(ee.Filter.eq("instrumentMode", "IW"))
    )
    if orbit_pass:
        collection = collection.filter(ee.Filter.eq("orbitProperties_pass", orbit_pass))
    return collection


def get_chirps_rainfall(aoi: ee.Geometry, start_date: str, end_date: str) -> ee.ImageCollection:
    """CHIRPS daily precipitation — Doc 0's rainfall data source."""
    return ee.ImageCollection(CHIRPS_COLLECTION).filterBounds(aoi).filterDate(start_date, end_date)


def get_era5_climate(aoi: ee.Geometry, start_date: str, end_date: str) -> ee.ImageCollection:
    """ERA5-Land daily aggregated climate reanalysis."""
    return ee.ImageCollection(ERA5_COLLECTION).filterBounds(aoi).filterDate(start_date, end_date)


def get_esa_worldcover(aoi: ee.Geometry) -> ee.Image:
    """ESA WorldCover v200 (10m global land cover), clipped to the AOI — a single static image, not a time series."""
    return ee.ImageCollection(WORLDCOVER_COLLECTION).first().clip(aoi)


def get_dem(aoi: ee.Geometry, source: str = "SRTM") -> ee.Image:
    """Doc 0's DEM sources: SRTM (default, near-global 30m) or ALOS (Japan's 30m DSM)."""
    if source == "SRTM":
        return ee.Image(SRTM_DEM_ASSET).clip(aoi)
    if source == "ALOS":
        collection = ee.ImageCollection(ALOS_DEM_COLLECTION).filterBounds(aoi).select("DSM")
        return collection.mosaic().setDefaultProjection(collection.first().projection()).clip(aoi)
    raise ValueError(f"Unknown DEM source '{source}'. Use 'SRTM' or 'ALOS'.")
