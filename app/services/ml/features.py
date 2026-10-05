"""
Feature extraction — assembles the tabular X (and optionally y) that
`app.services.ml.training` needs, by pulling pixel values from a stack
of named 2D raster layers (spectral indices, terrain derivatives,
rainfall surfaces, etc.) at a set of sampled locations.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.gee.sampling import SampleSet


def build_feature_dataframe(layers: dict[str, np.ndarray], sample: SampleSet) -> pd.DataFrame:
    """
    Extract each layer's pixel value at every sampled (row, col)
    location, producing one column per layer and one row per sample.
    All layers must share the same raster shape.
    """
    if not layers:
        raise ValueError("At least one layer is required.")

    shapes = {name: arr.shape for name, arr in layers.items()}
    unique_shapes = set(shapes.values())
    if len(unique_shapes) > 1:
        raise ValueError(f"All layers must share the same shape; got {shapes}")

    data = {name: arr[sample.rows, sample.cols] for name, arr in layers.items()}
    return pd.DataFrame(data)


def build_label_series(target_layer: np.ndarray, sample: SampleSet, name: str = "target") -> pd.Series:
    """Extract the target/response variable at the same sampled locations."""
    return pd.Series(target_layer[sample.rows, sample.cols], name=name)
