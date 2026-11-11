"""GEE boundary for the FIRRIS universal satellite workflow.

This module owns remote collection selection, date/AOI filtering, sensor-specific
preprocessing, projection normalization, and the bounded download into the local
ML pipeline.  It deliberately returns ordinary numpy rasters so the FIRRIS engine
and its validation/export code do not depend on Earth Engine objects.
"""
from __future__ import annotations

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
from app.services.gee.band_export import assemble_export, request_contract, EXPORT_FORMAT, VALIDITY_PREFIX
from app.services.gee.scene_qa import inspect_collection, inspect_static_image
from pyproj import CRS as ProjectionCRS
from pyproj.exceptions import CRSError

# Model features (Bundle 1 item 1.7): SAR, terrain and rainfall only. Sentinel-2 is the
# independent accuracy reference, so no optical index may be a model input.
DEFAULT_FEATURES = [
    "sar_vv_target",
    "sar_change",
    "elevation",
    "slope",
    "rainfall",
]
SOURCE_BANDS = ["source_sar_baseline", "source_sar_target", "label"]
# Exported after the label; never model features. Optical bands are reference-only and are
# excluded from pixel admission (cloud never removes a pixel from classification).
REFERENCE_BANDS = ["jrc_occurrence", "source_mndwi_target", "source_mndwi_baseline", "optical_reference"]
OPTICAL_REFERENCE_BANDS = ["source_mndwi_target", "source_mndwi_baseline", "optical_reference"]
OPTICAL_REFERENCE_POLICY = {
    "definition": ("flooded (1) = MNDWI > 0 on the target composite AND MNDWI <= 0 on the baseline composite "
                   "AND JRC occurrence < 90%; not flooded (0) = every other eligible pixel"),
    "mndwi": "(B3 - B11) / (B3 + B11), Sentinel-2 SR harmonized, SCL cloud/shadow/cirrus/snow masked, median composite",
    "scene_policy": "cloud <= max_cloud_pct and degraded MSI = 0% (query filter + per-scene assertion), both periods",
    "eligibility": "admitted pixels whose optical bands are valid at both dates",
    "independence": "optical indices are not model features; the reference never enters the feature matrix",
    "limitations": ["Optical water misses flooded vegetation and water under cloud",
                    "Reference restricted to pixels cloud-free at both dates",
                    "MNDWI > 0 threshold error",
                    "Reference and classifier observe slightly different dates",
                    "Not field-verified"],
}
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
JRC_WATER_ASSET = "JRC/GSW1_4/GlobalSurfaceWater"
# Companion asset of JRC GSW v1.4: per-pixel count of valid Landsat observations 1984-2021.
JRC_OBSERVATION_ASSET = "JRC/GSW1_4/Metadata"
JRC_MASK_POLICY = {
    "policy": "never-water=0 within Metadata valid_obs>0",
    "occurrence_asset": JRC_WATER_ASSET,
    "observation_asset": JRC_OBSERVATION_ASSET,
    "observation_band": "valid_obs",
    "nodata": "pixels with valid_obs = 0 or masked valid_obs stay nodata",
    "evidence": "FIRRIS_CRITICAL_SCIENTIFIC_FINDINGS_VERIFICATION.md §11.1",
}
FIRRIS_SCIENCE_VERSION = "firris-science-2"
OPTICAL_REFERENCE_MNDWI_BANDS = ("B11", "B3", "SCL")


def optical_flood_reference(mndwi_target, mndwi_baseline, occurrence):
    """Independent optical flood reference (1.7): new open water at target that is not permanent water.

    Pixels where either MNDWI composite or JRC occurrence is masked stay masked (not eligible).
    """
    return mndwi_target.gt(0).And(mndwi_baseline.lte(0)).And(occurrence.lt(90))


def jrc_occurrence_within_observed_footprint(occurrence, valid_obs):
    """Return JRC occurrence with never-water pixels as 0% where JRC observed the pixel.

    GlobalSurfaceWater masks pixels where water was never detected, which made all
    never-water land FIRRIS nodata (F1). Inside the JRC observation footprint a masked
    occurrence means 0%. The footprint is Metadata ``valid_obs > 0``; pixels JRC never
    observed (``valid_obs`` = 0 or masked) remain nodata. YearlyHistory is not usable
    for this bound because it also masks never-water pixels.
    """
    observed = valid_obs.gt(0)
    return occurrence.unmask(0).updateMask(observed)


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


def _download_image(image, aoi, output_path: Path, *, scale: float, crs: str, contract: dict) -> Path:
    url = image.getDownloadURL(
        {
            "region": aoi,
            "scale": scale,
            "crs": crs,
            "format": EXPORT_FORMAT,
            "filePerBand": True,
            "bands": contract["bands"] + contract["validity_bands"],
            "name": contract["filename_prefix"],
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
    if optical := sorted(set(requested) & set(INDEX_BANDS)):
        raise ValueError(f"Optical indices cannot be FIRRIS model features: {optical}. Sentinel-2 is the independent accuracy reference")
    unknown = sorted(set(requested) - set(DEFAULT_FEATURES))
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
    s1_target = ingestion.get_sentinel1_collection(aoi, target["start"], target["end"])
    s1_baseline = ingestion.get_sentinel1_collection(aoi, baseline["start"], baseline["end"])
    scene_qa = {
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
    s1_target=pin(scene_qa["sentinel_1_target"])
    s1_baseline=pin(scene_qa["sentinel_1_baseline"])
    # Sentinel-2 is acquired only for the independent reference. A period without a compliant
    # scene (or failing optical QA) makes the reference not assessable; it never fails the run.
    optical_reference_status = {}
    mndwi = {}
    for key, period in (("target", target), ("baseline", baseline)):
        try:
            collection = ingestion.get_sentinel2_collection(
                aoi, period["start"], period["end"], max_cloud_pct=max_cloud, require_zero_degraded_msi=True)
            record = inspect_collection(collection, sensor="Sentinel-2", period=period, aoi=aoi_geometry,
                required_bands=list(OPTICAL_REFERENCE_MNDWI_BANDS), max_cloud=max_cloud,
                collection_id=ingestion.SENTINEL2_COLLECTION)
        except ValueError as exc:
            optical_reference_status[key] = {"status": "unavailable", "reason": f"Sentinel-2 {key}: {exc}"}
            continue
        scene_qa[f"sentinel_2_{key}"] = record
        composite = preprocessing.clip_to_aoi(
            preprocessing.median_composite(pin(record).map(preprocessing.mask_sentinel2_clouds)), aoi)
        mndwi[key] = indices.compute_mndwi(composite)
        optical_reference_status[key] = {"status": "available", "scene_count": record["scene_count"]}
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
    # Never-water is 0% only inside the JRC observation footprint; unobserved pixels stay nodata.
    original_water=ingestion.ee.Image(JRC_WATER_ASSET)
    static_sources["water_occurrence"]=inspect_static_image(original_water,asset_id=JRC_WATER_ASSET,required_band="occurrence")
    original_observation=ingestion.ee.Image(JRC_OBSERVATION_ASSET)
    static_sources["water_observation"]=inspect_static_image(original_observation,asset_id=JRC_OBSERVATION_ASSET,required_band="valid_obs")
    water_observation = original_observation.select("valid_obs").clip(aoi)
    water = jrc_occurrence_within_observed_footprint(original_water.select("occurrence"), water_observation).clip(aoi)
    label = screening_pipeline.screen_binary_flood_extent(sar_change, slope, water).rename("label")
    reference_available = set(mndwi) == {"target", "baseline"}
    unavailable = label.multiply(0).selfMask()  # fully masked placeholder keeps the band contract fixed
    reference_layers = {
        "jrc_occurrence": water.rename("jrc_occurrence"),
        "source_mndwi_target": (mndwi.get("target") or unavailable).rename("source_mndwi_target"),
        "source_mndwi_baseline": (mndwi.get("baseline") or unavailable).rename("source_mndwi_baseline"),
        "optical_reference": (optical_flood_reference(mndwi["target"], mndwi["baseline"], water)
                              if reference_available else unavailable).rename("optical_reference"),
    }
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
    for role, image in (("dem", dem), ("water_occurrence", water), ("water_observation", water_observation)):
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
        "elevation": dem.rename("elevation"),
        "slope": slope.rename("slope"),
        "rainfall": rainfall,
    }
    stack = available[requested[0]]
    for name in requested[1:]:
        stack = stack.addBands(available[name])
    stack = stack.addBands(vv_baseline.rename("source_sar_baseline")).addBands(vv_target.rename("source_sar_target")).addBands(label)
    for name in REFERENCE_BANDS:
        stack = stack.addBands(reference_layers[name])
    stack = stack.clip(aoi).reproject(crs=crs, scale=scale)
    expected_bands=requested+SOURCE_BANDS+REFERENCE_BANDS
    admission_bands=[index for index, name in enumerate(expected_bands) if name not in OPTICAL_REFERENCE_BANDS]
    label_band=expected_bands.index("label")
    if stack.bandNames().getInfo()!=expected_bands:
        raise ValueError("Materialized remote band identities/order differ from the source contract")

    workspace.mkdir(parents=True, exist_ok=True)
    # Preserve source mask identity as well as samples: provider TIFF nodata=0
    # cannot distinguish a valid zero class/index from a masked pixel.
    validity_names = [VALIDITY_PREFIX + band for band in expected_bands]
    validity = stack.mask().gt(0).unmask(0, sameFootprint=False).rename(validity_names)
    transport = stack.addBands(validity)
    if transport.bandNames().getInfo() != expected_bands + validity_names:
        raise ValueError("Materialized remote validity identities/order differ from the source contract")
    contract = request_contract(transport.serialize(), aoi.serialize(), expected_bands, scale=scale, crs=crs)
    downloaded = _download_image(transport, aoi, workspace / "gee-feature-stack.download", scale=scale, crs=crs, contract=contract)
    raster_path, manifest_path, band_manifest = assemble_export(downloaded, contract)
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
            float(config.get("minimum_valid_coverage_pct", 70)), admission_bands=admission_bands, label_band=label_band)
        label_layer = np.where(valid_mask, values[label_band].filled(0), 0).astype(np.uint8)
        transform = source.transform
        output_crs = source.crs.to_string()
        source_rasters={name:np.asarray(values[expected_bands.index(name)].filled(np.nan),dtype=np.float32)
                        for name in ("source_sar_baseline","source_sar_target",*REFERENCE_BANDS)}
    source_artifacts={"acquired_feature_stack":downloaded, "band_identity_manifest":manifest_path}
    if raster_path!=downloaded: source_artifacts["extracted_feature_stack"]=raster_path
    acquisition_artifacts={key:{"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"size_bytes":path.stat().st_size,"filename":path.name} for key,path in source_artifacts.items()}

    target_count = scene_qa["sentinel_1_target"]["scene_count"]
    baseline_count = scene_qa["sentinel_1_baseline"]["scene_count"]
    minimum_coverage = float(config.get("minimum_valid_coverage_pct", 70))
    quality = {
        "status": "passed",
        **pixel_qa,
        "per_collection": scene_qa,
        "minimum_valid_coverage_pct": minimum_coverage,
        "admission_bands": [expected_bands[index] for index in admission_bands],
        "optical_reference": {
            "status": "available" if reference_available else "unavailable",
            "periods": optical_reference_status,
            "reason": None if reference_available else "; ".join(
                record["reason"] for record in optical_reference_status.values() if record["status"] != "available"),
        },
        "scene_counts": {
            "sentinel_2_target": scene_qa.get("sentinel_2_target", {}).get("scene_count", 0),
            "sentinel_2_baseline": scene_qa.get("sentinel_2_baseline", {}).get("scene_count", 0),
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
            "science_version":FIRRIS_SCIENCE_VERSION, "jrc_mask_policy":dict(JRC_MASK_POLICY),
            "acquisition_artifacts":acquisition_artifacts,
            "band_identity":expected_bands,
            "band_identity_delivery":band_manifest,
            "source_fidelity_scope":"Inspected scene IDs pinned before composition; provider metadata and received export bytes verified. Original provider source-byte checksums remain unavailable; metadata hashes are not pixel checksums.",
            "provider": "Google Earth Engine",
            "datasets": sorted(selected_datasets),
            "date_mode": date_mode,
            "date_policy": "end-exclusive; baseline precedes target; windows supplied explicitly",
            "corrections": CORRECTIONS,
            "indices": {"mndwi": {"sensor": "Sentinel-2 SR harmonized", "bands": INDEX_BANDS["mndwi"],
                "units": "dimensionless", "method": "existing approved normalized difference",
                "role": "independent accuracy reference only; not a model feature"}},
            "optical_reference_policy": dict(OPTICAL_REFERENCE_POLICY),
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
