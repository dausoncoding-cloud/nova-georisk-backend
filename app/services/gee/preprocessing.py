"""
Image Pre-processing — Doc 0 step 9's automatic pipeline. Implements
the pieces that are genuinely dataset-specific logic (cloud/shadow
masking per sensor, SAR speckle filtering); the more generic steps
(mosaicking, clipping, band selection) are thin one-line wrappers
kept here so every preprocessing call goes through one module.
"""
from __future__ import annotations

import ee


def mask_sentinel2_clouds(image: ee.Image) -> ee.Image:
    """
    Cloud/cirrus/shadow mask using the Sentinel-2 SCL (Scene
    Classification Layer) band. Mask 0 (no data), 1 (saturated/defective),
    3 (cloud shadow), 8/9 (cloud), 10 (cirrus), and 11 (snow/ice).
    Unclassified and dark-area pixels remain subject to the exported
    valid-coverage gate rather than being silently relabelled as cloud.
    """
    scl = image.select("SCL")
    mask = scl.neq(0)
    for invalid_class in (1, 3, 8, 9, 10, 11):
        mask = mask.And(scl.neq(invalid_class))
    return image.updateMask(mask)


def mask_landsat_clouds(image: ee.Image) -> ee.Image:
    """
    Cloud/shadow mask using the Landsat Collection 2 QA_PIXEL band:
    bits 0–5 mark fill, dilated cloud, cirrus, cloud, cloud shadow,
    and snow respectively.  All are invalid for optical indices.
    """
    qa = image.select("QA_PIXEL")
    mask = qa.bitwiseAnd(1).eq(0)
    for bit in range(1, 6):
        mask = mask.And(qa.bitwiseAnd(1 << bit).eq(0))
    return image.updateMask(mask)


def apply_speckle_filter(image: ee.Image, radius: int = 50) -> ee.Image:
    """
    SAR speckle filtering — Doc 0 step 9 'Speckle filtering (SAR)'.
    A focal-median filter is the standard, simplest despeckling
    approach for Sentinel-1 GRD (more elaborate filters like
    Refined Lee exist, but a focal median is the documented minimum
    Doc 0 asks for and is what most GIS pipelines default to).
    """
    return image.focal_median(radius, "circle", "meters").updateMask(image.mask())


def clip_to_aoi(image: ee.Image, aoi: ee.Geometry) -> ee.Image:
    """Doc 0 step 9 'Image clipping to AOI'."""
    return image.clip(aoi)


def mosaic_collection(collection: ee.ImageCollection) -> ee.Image:
    """Doc 0 step 9 'Image mosaicking' — merge an ImageCollection into one composite image."""
    return collection.mosaic()


def median_composite(collection: ee.ImageCollection) -> ee.Image:
    """Cloud-free-ish composite via per-pixel median across the (already cloud-masked) collection."""
    return collection.median()


def select_bands(image: ee.Image, bands: list[str]) -> ee.Image:
    return image.select(bands)
