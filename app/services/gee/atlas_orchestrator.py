"""
Flood Screening Atlas orchestrator — the generic replacement for the
one-off Ugalla scripts. Takes a project_id/aoi_id and produces the
same *kind* of screening product for whichever AOI is passed in,
writing outputs under `{output_root}/{project_id}/{aoi_id}/` rather
than a hardcoded location.

This is called from a Celery task (app/workers/celery_tasks.py), not
directly from an API request — GEE thumbnail export for ~15 layers
takes long enough to want real async task tracking (Queued -> Running
-> Completed -> Failed), matching every other long-running job in
this engine.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import ee
from PIL import Image
from shapely.geometry import shape

from app.services.gee import auth as auth_service
from app.services.gee import export as export_service
from app.services.gee import ingestion as ingestion_service
from app.services.gee import screening_pipeline as pipeline

logger = logging.getLogger(__name__)

SCREENING_CAVEAT = (
    "Screening product only — a fixed-weight multi-factor indicator meant to "
    "prioritize areas for field verification, not a validated flood-extent or "
    "flood-hazard map. Cross-check against observed flood extent / local "
    "knowledge before acting on it."
)


@dataclass
class AtlasManifest:
    result_id: str | None
    version: int
    project_id: str
    aoi_id: str
    generated_at: str
    target_period: dict
    baseline_period: dict
    bounds: list[float]
    crs: str | None
    provenance: dict
    products: list[dict] = field(default_factory=list)
    screening_caveat: str = SCREENING_CAVEAT

    def to_dict(self) -> dict:
        return {
            "result_id": self.result_id,
            "version": self.version,
            "project_id": self.project_id,
            "aoi_id": self.aoi_id,
            "generated_at": self.generated_at,
            "target_period": self.target_period,
            "baseline_period": self.baseline_period,
            "bounds": self.bounds,
            "crs": self.crs,
            "products": self.products,
            "provenance": self.provenance,
            "screening_caveat": self.screening_caveat,
            "legacy": False,
        }


# Visualization parameters per product — kept in one place so every
# caller (and every AOI) renders with the same, consistent palette.
_TRUE_COLOUR_VIS = {"min": 0, "max": 3000, "bands": ["B4", "B3", "B2"]}
_NDVI_VIS = {"min": -0.2, "max": 0.9, "palette": ["#8B4513", "#FFFF00", "#228B22", "#006400"]}
_MNDWI_VIS = {"min": -0.5, "max": 0.5, "palette": ["#8B4513", "#FFFFFF", "#00BFFF", "#00008B"]}
_NDBI_VIS = {"min": -0.3, "max": 0.3, "palette": ["#006400", "#FFFF00", "#8B0000"]}
_SAR_CHANGE_VIS = {"min": -6, "max": 6, "palette": ["#00008B", "#FFFFFF", "#8B0000"]}
_SEVERITY_VIS = {"min": 0, "max": 3, "palette": ["#006400", "#FFFF00", "#FFA500", "#FF0000"]}
_BINARY_VIS = {"min": 0, "max": 1, "palette": ["#FFFFFF", "#0000FF"]}
_ELEVATION_VIS = {"min": 0, "max": 2000, "palette": ["#006400", "#FFFF00", "#8B4513", "#FFFFFF"]}
_SLOPE_VIS = {"min": 0, "max": 30, "palette": ["#006400", "#FFFF00", "#FF0000"]}
_TPI_VIS = {"min": -20, "max": 20, "palette": ["#00008B", "#FFFFFF", "#8B0000"]}
_TWI_VIS = {"min": 0, "max": 20, "palette": ["#8B4513", "#FFFF00", "#00BFFF", "#00008B"]}
_DISTANCE_VIS = {"min": 0, "max": 5000, "palette": ["#00008B", "#FFFF00", "#8B4513"]}
_RAINFALL_VIS = {"min": 0, "max": 300, "palette": ["#FFFFFF", "#00BFFF", "#00008B"]}
_WORLDCOVER_VIS = {"min": 10, "max": 100}  # ESA WorldCover ships its own class palette
_HAZARD_INDEX_VIS = {"min": 0, "max": 1, "palette": ["#006400", "#90EE90", "#FFFF00", "#FFA500", "#FF0000"]}
_HAZARD_CLASS_VIS = {"min": 1, "max": 5, "palette": ["#006400", "#90EE90", "#FFFF00", "#FFA500", "#FF0000"]}


def generate_flood_screening_atlas(
    project_id: str,
    aoi_id: str,
    aoi_geometry: dict,
    target_start: str,
    target_end: str,
    baseline_start: str,
    baseline_end: str,
    output_root: Path,
    progress_callback=None,
    result_id: str | None = None,
    version: int = 1,
) -> AtlasManifest:
    """
    Generates the full screening atlas for one AOI and writes it under
    `{output_root}/{project_id}/{aoi_id}/`. `progress_callback`, if
    given, is called with an int 0-100 after each product so the
    caller (a Celery task) can update Task.progress_pct.
    """
    auth_service.initialize_gee()

    aoi = ingestion_service.build_aoi_geometry(aoi_geometry)
    output_dir = Path(output_root) / project_id / aoi_id
    if result_id:
        output_dir = output_dir / result_id
    output_dir.mkdir(parents=True, exist_ok=True)

    min_x, min_y, max_x, max_y = shape(aoi_geometry).bounds
    bounds = [float(min_x), float(min_y), float(max_x), float(max_y)]

    manifest = AtlasManifest(
        result_id=result_id,
        version=version,
        project_id=project_id,
        aoi_id=aoi_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        target_period={"start": target_start, "end": target_end},
        baseline_period={"start": baseline_start, "end": baseline_end},
        bounds=bounds,
        crs="EPSG:4326",
        provenance={
            "renderer": "Google Earth Engine getThumbURL",
            "pipeline": "nova-flood-screening-atlas",
            "pipeline_version": "1.0",
            "sources": [
                "COPERNICUS/S2_SR_HARMONIZED",
                "COPERNICUS/S1_GRD",
                "USGS/SRTMGL1_003",
                "UCSB-CHG/CHIRPS/DAILY",
                "ESA/WorldCover/v200",
                "JRC/GSW1_4/GlobalSurfaceWater",
                "WWF/HydroSHEDS/15ACC",
            ],
            "limitations": [
                "Rendered PNG preview, not a GeoTIFF, COG, tile pyramid, or queryable raster.",
                "No numeric nodata value is encoded in the PNG output.",
            ],
        },
    )

    s2_target = ingestion_service.get_sentinel2_collection(aoi, target_start, target_end)
    s1_target = ingestion_service.get_sentinel1_collection(aoi, target_start, target_end)
    s1_baseline = ingestion_service.get_sentinel1_collection(aoi, baseline_start, baseline_end)
    dem = ingestion_service.get_dem(aoi, source="SRTM")
    chirps = ingestion_service.get_chirps_rainfall(aoi, target_start, target_end)
    worldcover = ingestion_service.get_esa_worldcover(aoi)

    true_colour = pipeline.build_true_colour_composite(s2_target)
    ndvi = pipeline.build_ndvi_layer(s2_target)
    mndwi = pipeline.build_mndwi_layer(s2_target)
    ndbi = pipeline.build_ndbi_layer(s2_target)

    vv_before = pipeline.build_sar_vv_composite(s1_baseline)
    vv_after = pipeline.build_sar_vv_composite(s1_target)
    sar_change = pipeline.compute_sar_change(vv_before, vv_after)
    sar_severity = pipeline.classify_sar_change_severity(sar_change)

    slope = pipeline.compute_slope_degrees(dem)
    tpi = pipeline.compute_tpi(dem)
    water_occurrence = pipeline.get_water_occurrence(aoi)
    distance_to_water = pipeline.compute_distance_to_water_m(water_occurrence)
    twi = pipeline.compute_twi(dem, aoi)
    binary_extent = pipeline.screen_binary_flood_extent(sar_change, slope, water_occurrence)

    rainfall_total = chirps.select("precipitation").sum().rename("precipitation")

    hazard_index = pipeline.compute_hazard_screening_index(
        sar_candidate=binary_extent,
        elevation=dem,
        slope_degrees=slope,
        twi=twi,
        distance_to_water_m=distance_to_water,
        rainfall_mm=rainfall_total,
        ndvi=ndvi,
    )
    hazard_class = pipeline.classify_hazard_five_classes(hazard_index)

    layers: list[tuple[str, str, str, ee.Image, dict]] = [
        ("true_colour", "True-Colour Composite (Sentinel-2)", "01_true_colour.png", true_colour, _TRUE_COLOUR_VIS),
        ("ndvi", "NDVI (Vegetation)", "02_ndvi.png", ndvi, _NDVI_VIS),
        ("mndwi", "MNDWI (Surface Water)", "03_mndwi.png", mndwi, _MNDWI_VIS),
        ("ndbi", "NDBI (Built-up)", "04_ndbi.png", ndbi, _NDBI_VIS),
        ("sar_change", "SAR Backscatter Change (dB)", "05_sar_change.png", sar_change, _SAR_CHANGE_VIS),
        ("sar_severity", "SAR Change Severity (4-class)", "06_sar_severity.png", sar_severity, _SEVERITY_VIS),
        ("binary_extent", "Screening Binary Flood Extent", "07_binary_extent.png", binary_extent, _BINARY_VIS),
        ("elevation", "Elevation (SRTM)", "08_elevation.png", dem, _ELEVATION_VIS),
        ("slope", "Slope (degrees)", "09_slope.png", slope, _SLOPE_VIS),
        ("tpi", "Topographic Position Index", "10_tpi.png", tpi, _TPI_VIS),
        ("twi", "Topographic Wetness Index", "11_twi.png", twi, _TWI_VIS),
        ("distance_to_water", "Distance to Surface Water (m)", "12_distance_to_water.png", distance_to_water, _DISTANCE_VIS),
        ("rainfall", "Total Rainfall, Target Period (mm)", "13_rainfall.png", rainfall_total, _RAINFALL_VIS),
        ("worldcover", "ESA WorldCover Land Cover", "14_worldcover.png", worldcover, _WORLDCOVER_VIS),
        ("hazard_index", "Hazard Screening Index (0-1)", "15_hazard_index.png", hazard_index, _HAZARD_INDEX_VIS),
        ("hazard_class", "Hazard Screening Class (1-5)", "16_hazard_class.png", hazard_class, _HAZARD_CLASS_VIS),
    ]

    units_by_key = {
        "ndvi": "dimensionless",
        "mndwi": "dimensionless",
        "ndbi": "dimensionless",
        "sar_change": "dB",
        "sar_severity": "class",
        "binary_extent": "binary class",
        "elevation": "m",
        "slope": "degrees",
        "tpi": "m",
        "twi": "dimensionless",
        "distance_to_water": "m",
        "rainfall": "mm",
        "worldcover": "class",
        "hazard_index": "dimensionless",
        "hazard_class": "class",
    }

    total = len(layers)
    for i, (key, label, filename, image, vis_params) in enumerate(layers, start=1):
        output_path = output_dir / filename
        try:
            export_service.render_thumbnail(image, aoi, output_path, vis_params=vis_params)
            with Image.open(output_path) as rendered:
                width, height = rendered.size
            palette = list(vis_params.get("palette", []))
            legend = None
            if palette:
                legend = {
                    "type": "continuous",
                    "minimum": vis_params.get("min"),
                    "maximum": vis_params.get("max"),
                    "palette": palette,
                    "entries": [],
                }
            manifest.products.append(
                {
                    "key": key,
                    "label": label,
                    "url": (
                        f"/api/v1/results/{result_id}/products/{key}"
                        if result_id
                        else f"/outputs/{project_id}/{aoi_id}/{filename}"
                    ),
                    "filename": filename,
                    "bounds": bounds,
                    "crs": "EPSG:4326",
                    "width": width,
                    "height": height,
                    "units": units_by_key.get(key),
                    "nodata": None,
                    "legend": legend,
                }
            )
        except Exception:
            logger.exception("Failed to render layer '%s' for project=%s aoi=%s", key, project_id, aoi_id)
            raise
        if progress_callback:
            progress_callback(int(i / total * 100))

    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(json.dumps(manifest.to_dict(), indent=2))

    return manifest
