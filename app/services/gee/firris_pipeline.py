"""GEE boundary for the FIRRIS universal satellite workflow.

This module owns remote collection selection, date/AOI filtering, sensor-specific
preprocessing, projection normalization, and the bounded download into the local
ML pipeline.  It deliberately returns ordinary numpy rasters so the FIRRIS engine
and its validation/export code do not depend on Earth Engine objects.
"""
from __future__ import annotations

import shutil
import hashlib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import requests
from rasterio.crs import CRS

from app.services.gee import auth, indices, ingestion, preprocessing, screening_pipeline
from app.services.gee.firris_contracts import INDEX_BANDS, CORRECTIONS, periods, validate_aoi, validate_grid, assess_pixels
from app.services.gee.scene_qa import inspect_collection, inspect_static_image
from pyproj import CRS as ProjectionCRS
from pyproj.exceptions import CRSError

DEFAULT_FEATURES = [
    "sar_vv_target",
    "sar_change",
    "ndvi",
    "mndwi",
    "ndbi",
    "elevation",
    "slope",
    "rainfall",
]
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
JRC_WATER_ASSET = "JRC/GSW1_4/GlobalSurfaceWater"


@dataclass(frozen=True)
class GEEFeatureStack:
    feature_layers: dict[str, np.ndarray]
    label_layer: np.ndarray
    valid_mask: np.ndarray
    transform: rasterio.Affine
    crs: str
    quality: dict[str, Any]
    provenance: dict[str, Any]
    source_artifacts: dict[str, Path] = field(default_factory=dict)
    source_rasters: dict[str, np.ndarray] = field(default_factory=dict)


def _download_image(image, aoi, output_path: Path, *, scale: float, crs: str) -> Path:
    url = image.getDownloadURL(
        {
            "region": aoi,
            "scale": scale,
            "crs": crs,
            "format": "GEO_TIFF",
            "filePerBand": False,
        }
    )
    response = requests.get(url, stream=True, timeout=(30, 300))
    try:
        response.raise_for_status()
        declared_size = int(response.headers.get("content-length", "0") or 0)
        if not 0 <= declared_size <= MAX_DOWNLOAD_BYTES:
            raise ValueError("GEE export exceeds the bounded synchronous download limit.")
        downloaded = 0
        with output_path.open("wb") as target:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD_BYTES:
                    raise ValueError("GEE export exceeds the bounded synchronous download limit.")
                target.write(chunk)
        if not downloaded or (declared_size and declared_size != downloaded):
            raise ValueError("Received GEE export is empty or differs from its declared byte length.")
    finally:
        response.close()
    return output_path


def _resolve_tiff(downloaded: Path) -> Path:
    if not zipfile.is_zipfile(downloaded):
        return downloaded
    extraction_dir = downloaded.parent / "gee-extracted"
    extraction_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(downloaded) as archive:
        candidates = [item for item in archive.infolist() if item.filename.lower().endswith((".tif", ".tiff"))]
        if len(candidates) != 1:
            raise ValueError("GEE must return one multiband GeoTIFF for the FIRRIS feature stack.")
        member = candidates[0]
        if member.file_size > MAX_DOWNLOAD_BYTES or member.flag_bits & 1:
            raise ValueError("GEE archive member exceeds protected capacity or is encrypted")
        safe_name = Path(member.filename).name
        extracted = extraction_dir / safe_name
        with archive.open(member) as source, extracted.open("wb") as target:
            shutil.copyfileobj(source, target)
    return extracted


def _fetch_feature_stack(config: dict[str, Any], aoi_geometry: dict, workspace: Path) -> GEEFeatureStack:
    """Build and download a quality-masked FIRRIS feature stack from GEE.

    The current supervised label option is the existing SAR screening mask.  It
    is recorded as a pseudo-label in provenance and must not be represented as
    independent ground-truth validation.
    """
    date_periods, date_mode = periods(config)
    target = date_periods["target_period"]
    baseline = date_periods["baseline_period"]
    max_cloud = float(config.get("max_cloud_pct", 20))
    if not 0 <= max_cloud <= 100:
        raise ValueError("max_cloud_pct must be between 0 and 100.")
    scale = float(config.get("scale", 30))
    if not 1 <= scale <= 1000:
        raise ValueError("GEE scale must be between 1 and 1000 metres.")
    crs = str(config.get("target_crs", "EPSG:4326"))
    dem_source = str(config.get("dem_source", "SRTM"))
    if dem_source not in {"SRTM", "ALOS"}:
        raise ValueError("Unsupported FIRRIS DEM source")
    dem_dataset = ingestion.SRTM_DEM_ASSET if dem_source == "SRTM" else ingestion.ALOS_DEM_COLLECTION
    required_datasets = {
        ingestion.SENTINEL1_COLLECTION,
        ingestion.SENTINEL2_COLLECTION,
        ingestion.CHIRPS_COLLECTION,
        dem_dataset,
        JRC_WATER_ASSET,
    }
    dataset_choices = config.get("datasets") or sorted(required_datasets)
    if len(dataset_choices) != len(set(dataset_choices)):
        raise ValueError("Duplicate dataset choices are unsupported")
    selected_datasets = set(dataset_choices)
    allowed_datasets = {
        ingestion.SENTINEL1_COLLECTION,
        ingestion.SENTINEL2_COLLECTION,
        ingestion.CHIRPS_COLLECTION,
        ingestion.SRTM_DEM_ASSET,
        ingestion.ALOS_DEM_COLLECTION,
        JRC_WATER_ASSET,
    }
    if unknown_datasets := sorted(selected_datasets - allowed_datasets):
        raise ValueError(f"Unsupported GEE datasets: {unknown_datasets}")
    if missing_datasets := sorted(required_datasets - selected_datasets):
        raise ValueError(f"GEE FIRRIS workflow is missing required datasets: {missing_datasets}")
    if selected_datasets != required_datasets:
        raise ValueError("Dataset selection includes an unused/conflicting DEM")
    requested = list(config.get("features") or DEFAULT_FEATURES)
    if len(requested) != len(set(requested)):
        raise ValueError("Duplicate FIRRIS features are unsupported")
    preprocessing_config = dict(config.get("preprocessing") or {})
    required_preprocessing = ("cloud_mask", "sar_speckle_filter", "normalize_projection", "clip_to_aoi")
    if disabled := [key for key in required_preprocessing if preprocessing_config.get(key, True) is not True]:
        raise ValueError(f"FIRRIS GEE preprocessing cannot disable required safeguards: {', '.join(disabled)}")
    speckle_radius = int(preprocessing_config.get("sar_speckle_radius_m", 50))
    if not 1 <= speckle_radius <= 500:
        raise ValueError("SAR speckle radius must be between 1 and 500 metres.")
    unknown = sorted(set(requested) - (set(DEFAULT_FEATURES) | set(INDEX_BANDS)))
    if unknown:
        raise ValueError(f"Unsupported GEE FIRRIS features: {unknown}")

    validate_aoi(aoi_geometry)
    minimum_coverage = float(config.get("minimum_valid_coverage_pct", 70))
    if not np.isfinite(minimum_coverage) or not 0 <= minimum_coverage <= 100:
        raise ValueError("Minimum valid coverage must be finite and between 0 and 100")
    projection = ProjectionCRS.from_user_input(crs)
    if not (projection.is_projected or projection.is_geographic):
        raise ValueError("Unsupported output CRS")
    auth.initialize_gee()
    aoi = ingestion.build_aoi_geometry(aoi_geometry)
    s2 = ingestion.get_sentinel2_collection(
        aoi, target["start"], target["end"], max_cloud_pct=max_cloud
    )
    s1_target = ingestion.get_sentinel1_collection(aoi, target["start"], target["end"])
    s1_baseline = ingestion.get_sentinel1_collection(aoi, baseline["start"], baseline["end"])
    optical_bands = sorted({"SCL"} | {band for name in requested if name in INDEX_BANDS for band in INDEX_BANDS[name]})
    scene_qa = {
        "sentinel_2_target": inspect_collection(s2, sensor="Sentinel-2", period=target,
            aoi=aoi_geometry, required_bands=optical_bands, max_cloud=max_cloud, collection_id=ingestion.SENTINEL2_COLLECTION),
        "sentinel_1_target": inspect_collection(s1_target, sensor="Sentinel-1", period=target,
            aoi=aoi_geometry, required_bands=["VV"], collection_id=ingestion.SENTINEL1_COLLECTION),
        "sentinel_1_baseline": inspect_collection(s1_baseline, sensor="Sentinel-1", period=baseline,
            aoi=aoi_geometry, required_bands=["VV"], collection_id=ingestion.SENTINEL1_COLLECTION),
    }
    orbit_sets = [{record["relative_orbit"] for record in scene_qa[key]["scenes"]}
                  for key in ("sentinel_1_target", "sentinel_1_baseline")]
    if orbit_sets[0] != orbit_sets[1] or len(orbit_sets[0]) != 1:
        raise ValueError("SAR change requires one matching relative orbit in both periods")
    def pin(collection_record):
        return ingestion.ee.ImageCollection.fromImages([ingestion.ee.Image(record["scene_id"]) for record in collection_record["scenes"]])
    s2=pin(scene_qa["sentinel_2_target"])
    s1_target=pin(scene_qa["sentinel_1_target"])
    s1_baseline=pin(scene_qa["sentinel_1_baseline"])
    s2_composite = preprocessing.clip_to_aoi(
        preprocessing.median_composite(s2.map(preprocessing.mask_sentinel2_clouds)), aoi
    )
    vv_target = preprocessing.apply_speckle_filter(
        screening_pipeline.build_sar_vv_composite(s1_target), radius=speckle_radius
    )
    vv_baseline = preprocessing.apply_speckle_filter(
        screening_pipeline.build_sar_vv_composite(s1_baseline), radius=speckle_radius
    )
    sar_change = screening_pipeline.compute_sar_change(vv_baseline, vv_target)
    static_sources={}
    if dem_source=="SRTM":
        original_dem=ingestion.ee.Image(ingestion.SRTM_DEM_ASSET)
        static_sources["dem"]=inspect_static_image(original_dem,asset_id=ingestion.SRTM_DEM_ASSET,required_band="elevation")
        dem=original_dem.clip(aoi)
    else:
        # ALOS is a static tile mosaic. Its native tile lineage is required;
        # acquisition dates are not falsely interpreted as event observations.
        collection=ingestion.ee.ImageCollection(ingestion.ALOS_DEM_COLLECTION).filterBounds(aoi).select("DSM")
        count=int(collection.size().getInfo())
        if not 1<=count<=500: raise ValueError("ALOS source tile collection is empty or exceeds bounded capacity")
        tile_metadata=collection.toList(count).getInfo()
        if not isinstance(tile_metadata,list) or len(tile_metadata)!=count: raise ValueError("ALOS tile lineage is incomplete")
        tiles=[]
        identifiers=set()
        for item in tile_metadata:
            if not isinstance(item,dict) or not isinstance(item.get("id"),str): raise ValueError("ALOS tile metadata/identity is malformed")
            asset_id=item["id"]
            if not asset_id.startswith(ingestion.ALOS_DEM_COLLECTION+"/") or asset_id in identifiers: raise ValueError("ALOS tile identity is invalid or duplicated")
            identifiers.add(asset_id)
            image=ingestion.ee.Image(asset_id)
            tiles.append(inspect_static_image(image,asset_id=asset_id,required_band="DSM"))
        from shapely.geometry import shape
        from shapely.ops import unary_union
        footprints=[]
        for item in tile_metadata:
            footprint=item.get("properties",{}).get("system:footprint")
            if not isinstance(footprint,dict): raise ValueError("ALOS native footprint is unavailable")
            if footprint.get("type")=="LinearRing": footprint={"type":"Polygon","coordinates":[footprint["coordinates"]]}
            polygon=shape(footprint)
            if polygon.is_empty or not polygon.is_valid: raise ValueError("ALOS native footprint is invalid")
            footprints.append(polygon)
        if not unary_union(footprints).covers(shape(aoi_geometry)): raise ValueError("ALOS source tiles do not cover AOI")
        pinned=ingestion.ee.ImageCollection.fromImages([ingestion.ee.Image(item["asset_id"]) for item in tiles])
        dem=pinned.mosaic().setDefaultProjection(pinned.first().projection()).clip(aoi)
        static_sources["dem"]={"collection_id":ingestion.ALOS_DEM_COLLECTION,"tiles":tiles,"status":"passed"}
    slope = screening_pipeline.compute_slope_degrees(dem)
    # Do not use the screening helper's historical unmask(0): unknown is nodata.
    original_water=ingestion.ee.Image(JRC_WATER_ASSET)
    static_sources["water_occurrence"]=inspect_static_image(original_water,asset_id=JRC_WATER_ASSET,required_band="occurrence")
    water = original_water.select("occurrence").clip(aoi)
    label = screening_pipeline.screen_binary_flood_extent(sar_change, slope, water).rename("label")
    rainfall_collection = ingestion.get_chirps_rainfall(aoi, target["start"], target["end"])
    scene_qa["chirps_target"] = inspect_collection(rainfall_collection, sensor="CHIRPS", period=target,
        aoi=aoi_geometry, required_bands=["precipitation"], collection_id=ingestion.CHIRPS_COLLECTION)
    rainfall_collection=pin(scene_qa["chirps_target"])
    from datetime import date, timedelta
    days = {record["acquired_at"] for record in scene_qa["chirps_target"]["scenes"]}
    day = date.fromisoformat(target["start"])
    expected_days = set()
    while day < date.fromisoformat(target["end"]):
        expected_days.add(day.isoformat())
        day += timedelta(days=1)
    if days != expected_days or len(days) != scene_qa["chirps_target"]["scene_count"]:
        raise ValueError("Rainfall daily collection has missing or duplicate dates")
    native_projections = {}
    from rasterio import Affine
    for role, image in (("dem", dem), ("water_occurrence", water)):
        metadata = image.projection().getInfo()
        try:
            validate_grid(metadata["crs"], Affine(*metadata["transform"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Static source native CRS/grid metadata is invalid") from exc
        native_projections[role] = metadata
    rainfall = (
        rainfall_collection
        .select("precipitation")
        .sum()
        .rename("rainfall")
    )
    available = {
        "sar_vv_target": vv_target.rename("sar_vv_target"),
        "sar_change": sar_change.rename("sar_change"),
        "ndvi": indices.compute_ndvi(s2_composite).rename("ndvi"),
        "mndwi": indices.compute_mndwi(s2_composite).rename("mndwi"),
        "ndbi": indices.compute_ndbi(s2_composite).rename("ndbi"),
        "elevation": dem.rename("elevation"),
        "slope": slope.rename("slope"),
        "rainfall": rainfall,
    }
    for name in requested:
        if name in INDEX_BANDS:
            available[name] = getattr(indices, "compute_" + name)(s2_composite).rename(name)
    stack = available[requested[0]]
    for name in requested[1:]:
        stack = stack.addBands(available[name])
    stack = stack.addBands(vv_baseline.rename("source_sar_baseline")).addBands(vv_target.rename("source_sar_target")).addBands(label).clip(aoi).reproject(crs=crs, scale=scale)
    expected_bands=requested+["source_sar_baseline","source_sar_target","label"]
    if stack.bandNames().getInfo()!=expected_bands:
        raise ValueError("Materialized remote band identities/order differ from the source contract")

    workspace.mkdir(parents=True, exist_ok=True)
    downloaded = _download_image(stack, aoi, workspace / "gee-feature-stack.download", scale=scale, crs=crs)
    raster_path = _resolve_tiff(downloaded)
    with rasterio.open(raster_path) as source:
        if source.crs is None or source.crs != CRS.from_user_input(crs):
            raise ValueError("GEE export CRS does not match the requested analysis CRS.")
        if source.transform.b != 0 or source.transform.d != 0 or source.transform.a <= 0 or source.transform.e >= 0:
            raise ValueError("GEE export requires a north-up, nonrotated grid.")
        validate_grid(source.crs, source.transform, scale)
        values = source.read(masked=True).astype(np.float32)
        if list(source.descriptions)!=expected_bands:
            raise ValueError("Downloaded feature stack lacks exact named-band fidelity")
        if values.shape[0] != len(expected_bands):
            raise ValueError("GEE feature stack band count does not match the requested feature contract.")
        feature_layers = {name: np.asarray(values[index].filled(np.nan), dtype=np.float32) for index, name in enumerate(requested)}
        valid_mask, pixel_qa = assess_pixels(values, aoi_geometry, source.transform, source.crs,
            float(config.get("minimum_valid_coverage_pct", 70)))
        label_layer = np.where(valid_mask, values[-1].filled(0), 0).astype(np.uint8)
        transform = source.transform
        output_crs = source.crs.to_string()
        source_rasters={name:np.asarray(values[len(requested)+index].filled(np.nan),dtype=np.float32) for index,name in enumerate(("source_sar_baseline","source_sar_target"))}
    source_artifacts={"acquired_feature_stack":downloaded}
    if raster_path!=downloaded: source_artifacts["extracted_feature_stack"]=raster_path
    acquisition_artifacts={key:{"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"size_bytes":path.stat().st_size,"filename":path.name} for key,path in source_artifacts.items()}

    target_count = scene_qa["sentinel_1_target"]["scene_count"]
    baseline_count = scene_qa["sentinel_1_baseline"]["scene_count"]
    optical_count = scene_qa["sentinel_2_target"]["scene_count"]
    minimum_coverage = float(config.get("minimum_valid_coverage_pct", 70))
    quality = {
        "status": "passed",
        **pixel_qa,
        "per_collection": scene_qa,
        "minimum_valid_coverage_pct": minimum_coverage,
        "scene_counts": {
            "sentinel_2_target": optical_count,
            "sentinel_1_target": target_count,
            "sentinel_1_baseline": baseline_count,
        },
        "max_cloud_pct": max_cloud,
    }
    return GEEFeatureStack(
        feature_layers=feature_layers,
        label_layer=label_layer,
        valid_mask=valid_mask,
        transform=transform,
        crs=output_crs,
        quality=quality,
        source_artifacts=source_artifacts,
        source_rasters=source_rasters,
        provenance={
            "per_scene_lineage":scene_qa, "static_source_lineage":static_sources,
            "acquisition_artifacts":acquisition_artifacts,
            "band_identity":expected_bands,
            "source_fidelity_scope":"Inspected scene IDs pinned before composition; provider metadata and received export bytes verified. Original provider source-byte checksums remain unavailable; metadata hashes are not pixel checksums.",
            "provider": "Google Earth Engine",
            "datasets": sorted(selected_datasets),
            "date_mode": date_mode,
            "date_policy": "end-exclusive; baseline precedes target; windows supplied explicitly",
            "corrections": CORRECTIONS,
            "indices": {name: {"sensor": "Sentinel-2 SR harmonized", "bands": INDEX_BANDS[name],
                "units": "dimensionless", "method": "existing approved normalized difference"}
                for name in requested if name in INDEX_BANDS},
            "excluded_indices": ["BAI", "NBR", "dNBR", "LST (no thermal band on selected sensor)"],
            "compositing": "per-band temporal median of valid observations; spatial overlap participates in median",
            "resampling": "Earth Engine default nearest neighbour; one final export grid",
            "band_harmonization": "explicit Sentinel-2 band names; native 10/20m bands; no cross-sensor substitution",
            "target_period": target,
            "baseline_period": baseline,
            "aoi_filter": True,
            "optical_mask": {"sensor": "Sentinel-2 SR harmonized", "band": "SCL",
                             "excluded_classes": [0, 1, 3, 8, 9, 10, 11],
                             "policy": "no-data, defective, shadow, cloud, cirrus, snow/ice excluded"},
            "optical_surface_reflectance": "provider Level-2A surface-reflectance collection; no additional terrain correction claimed",
            "gap_policy": "masked or missing pixels remain nodata; no synthetic gap filling",
            "sar_preprocessing": {"method": "focal-median speckle filter", "radius_m": speckle_radius},
            "projection_normalization": {"crs": crs, "scale_m": scale, "native_static_sources": native_projections,
                "alignment": "one exported north-up affine shared by every band; validated after download"},
            "label_source": "SAR screening pseudo-label; not independent ground truth",
        },
    )


class FIRRISQualityError(ValueError):
    """Safe, persistable fail-closed acquisition QA outcome."""
    def __init__(self, message):
        super().__init__(message)
        self.quality_record = {"status": "failed", "policy_version": "bundle1-v1",
                               "failure_code": "FIRRIS_ACQUISITION_QA_FAILED", "analysis_inputs_released": False}


def fetch_feature_stack(config, aoi_geometry, workspace):
    try:
        return _fetch_feature_stack(config, aoi_geometry, workspace)
    except (ValueError, CRSError) as exc:
        raise FIRRISQualityError(str(exc)) from exc
    except (rasterio.errors.RasterioError, requests.RequestException, zipfile.BadZipFile, OSError, TypeError, KeyError) as exc:
        raise FIRRISQualityError("Remote source metadata/export could not be verified; analysis inputs not released") from exc
