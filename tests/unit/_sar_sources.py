"""Synthetic SAR source rasters for workflow tests (firris-science-3 derives the HSBA label from them).

Land: VV about -8 dB in both dates. Water: VV about -20 dB on the target date only, so the target image is
bimodal where water is present and the change image is bimodal in the same tiles.
"""
import numpy as np


def sar_sources(water: np.ndarray, seed: int = 0) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    water = np.asarray(water, dtype=bool)
    baseline = rng.normal(-8.0, 1.0, water.shape)
    target = baseline + rng.normal(0.0, 0.3, water.shape)
    target[water] = rng.normal(-20.0, 1.0, int(water.sum()))
    return {"source_sar_target": target.astype("float32"), "source_sar_baseline": baseline.astype("float32"),
            "jrc_occurrence": np.zeros(water.shape, dtype="float32")}
