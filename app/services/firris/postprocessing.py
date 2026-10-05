"""Opt-in categorical map generalization, never scientific prediction replacement.

A square pixel neighbourhood defines support, not a physical flood-size threshold.
Boundary/nodata-adjacent cells remain unchanged whenever the complete dependency
footprint is unavailable. No nodata pixel may become valid or flooded.
"""
import hashlib

import numpy as np
from scipy import ndimage

from app.schemas.analyses import FIRRISPostprocessingConfig


def generalize_extent(values, valid_mask, configuration):
    policy = FIRRISPostprocessingConfig.model_validate(configuration or {})
    raw = np.asarray(values)
    valid = np.asarray(valid_mask)
    if raw.ndim != 2 or valid.shape != raw.shape or valid.dtype != np.bool_:
        raise ValueError("Cleanup requires a 2D class grid and identically shaped boolean valid mask")
    if not np.isin(raw[valid], [0, 1]).all() or not valid.any():
        raise ValueError("Cleanup requires finite binary observed/predicted valid cells")
    result = np.where(valid, raw, 0).astype(np.uint8)
    record = {"applied": bool(policy.operations), "operations": policy.operations,
              "purpose": "categorical map generalization; raw prediction/score/validation unchanged",
              "policy_reference": policy.policy_reference,
              "policy_reference_status": "operator supplied; independent scientific review not asserted",
              "window_pixels": policy.window_pixels, "iterations_per_operation": 1,
              "edge_gap_policy": "preserve original cells unless complete dependency footprint is valid",
              "nodata_policy": "preserve; never fill", "changed_cells": 0,
              "source_sha256": hashlib.sha256(result.tobytes()).hexdigest(),
              "valid_mask_sha256": hashlib.sha256(valid.tobytes()).hexdigest(),
              "reference": "https://docs.scipy.org/doc/scipy-1.14.1/reference/ndimage.html"}
    structure = np.ones((policy.window_pixels, policy.window_pixels), dtype=bool)
    for operation in policy.operations:
        if operation == "majority":
            support = ndimage.binary_erosion(valid, structure=structure, border_value=0)
            counts = ndimage.convolve(result.astype(np.int16), structure.astype(np.int16), mode="constant", cval=0)
            candidate = counts > structure.size // 2
        else:
            # Opening/closing each depend on two neighbourhood passes. Merely
            # masking the result would let unknown pixels influence valid edges.
            radius = policy.window_pixels // 2
            footprint = np.ones((4 * radius + 1, 4 * radius + 1), dtype=bool)
            support = ndimage.binary_erosion(valid, structure=footprint, border_value=0)
            candidate = getattr(ndimage, "binary_" + operation)(result.astype(bool), structure=structure, iterations=1)
        result[support] = candidate[support]
    result[~valid] = 0
    record["changed_cells"] = int(np.count_nonzero((result != raw) & valid))
    record["output_sha256"] = hashlib.sha256(result.tobytes()).hexdigest()
    return result, record
