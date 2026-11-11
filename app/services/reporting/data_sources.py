"""Shared descriptions and credits of FIRRIS provider datasets (overview, map packages, reports)."""
from __future__ import annotations

SOURCES = {
    "COPERNICUS/S1_GRD": ("SAR backscatter, target and baseline (model features and screening labels)", "10 m (IW GRD)", "copernicus"),
    "COPERNICUS/S2_SR_HARMONIZED": ("Optical surface reflectance (MNDWI) for the independent reference only", "10–20 m", "copernicus"),
    "UCSB-CHG/CHIRPS/DAILY": ("Daily rainfall over the target window", "0.05° (~5.5 km)", "CHIRPS, UC Santa Barbara Climate Hazards Center"),
    "USGS/SRTMGL1_003": ("Elevation and slope", "1 arc-second (~30 m)", "SRTM, NASA/USGS"),
    "JAXA/ALOS/AW3D30/V3_2": ("Elevation and slope", "1 arc-second (~30 m)", "ALOS World 3D-30m, JAXA"),
    "JRC/GSW1_4/GlobalSurfaceWater": ("Historical surface-water occurrence (permanent-water exclusion)", "30 m", "JRC Global Surface Water v1.4, EC JRC / Google"),
    "JRC/GSW1_4/Metadata": ("JRC observation footprint (valid_obs) bounding the never-water correction", "30 m", "JRC Global Surface Water v1.4, EC JRC / Google"),
}


def datasets_with_companions(provenance: dict) -> list[str]:
    datasets = list(provenance.get("datasets") or [])
    if "JRC/GSW1_4/GlobalSurfaceWater" in datasets and provenance.get("science_version") == "firris-science-2":
        datasets.append("JRC/GSW1_4/Metadata")
    return datasets


def credit(dataset: str, years: list[str] | None = None) -> str:
    text = SOURCES.get(dataset, ("", "", dataset))[2]
    if text == "copernicus":
        return f"Contains modified Copernicus Sentinel data {', '.join(years)}" if years else "Contains modified Copernicus Sentinel data"
    return text
