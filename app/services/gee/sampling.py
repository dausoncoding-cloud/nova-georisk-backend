"""
Sampling generator — Doc 0 "Universal Satellite Image Analysis Workflow
& Sampling Strategy": stratified random sampling, 5,000 recommended
samples, proportional allocation, minimum 30 samples/class, 70/30
train/test split.

Operates on any 2D classified raster (numpy array of class labels) —
the actual pixel values would come from a land-cover/risk-class layer
pulled from GEE, but the sampling logic itself has no GEE dependency
and is fully testable on a synthetic raster.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DEFAULT_TOTAL_SAMPLES = 5000
DEFAULT_MIN_PER_CLASS = 30
DEFAULT_TRAIN_SPLIT = 0.70


@dataclass
class SampleSet:
    """Sampled pixel locations, as (row, col) coordinate arrays, with class labels."""

    rows: np.ndarray
    cols: np.ndarray
    labels: np.ndarray

    @property
    def n(self) -> int:
        return len(self.labels)

    def per_class_counts(self) -> dict:
        classes, counts = np.unique(self.labels, return_counts=True)
        return dict(zip(classes.tolist(), counts.tolist()))


@dataclass
class TrainTestSplit:
    train: SampleSet
    test: SampleSet
    train_split: float = DEFAULT_TRAIN_SPLIT


def _proportional_allocation(class_counts: dict, total_samples: int, min_per_class: int) -> dict:
    """
    Allocate `total_samples` across classes proportional to their
    population in the raster, with a floor of `min_per_class` per
    class (Doc 0: "minimum 30 samples/class") — never asking for more
    samples than a class actually has available.
    """
    total_population = sum(class_counts.values())
    allocation = {}
    for cls, population in class_counts.items():
        proportional = int(round(total_samples * population / total_population))
        allocation[cls] = max(min_per_class, proportional)
        allocation[cls] = min(allocation[cls], population)  # can't sample more than exists
    return allocation


def stratified_random_sample(
    strata: np.ndarray,
    total_samples: int = DEFAULT_TOTAL_SAMPLES,
    min_per_class: int = DEFAULT_MIN_PER_CLASS,
    random_seed: int = 12345,
    valid_mask: np.ndarray | None = None,
) -> SampleSet:
    """
    Stratified random sampling over a classified raster, proportional
    allocation — Doc 0's default and recommended sampling method.
    `valid_mask`, if given, restricts sampling to True cells (e.g.
    excluding nodata/cloud-masked pixels).
    """
    strata = np.asarray(strata)
    if valid_mask is not None:
        valid_mask = np.asarray(valid_mask, dtype=bool)
        if valid_mask.shape != strata.shape:
            raise ValueError("valid_mask must have the same shape as strata.")
    else:
        valid_mask = np.ones(strata.shape, dtype=bool)

    rng = np.random.default_rng(random_seed)

    classes = np.unique(strata[valid_mask])
    class_pixel_indices = {
        cls: np.argwhere(valid_mask & (strata == cls)) for cls in classes
    }
    class_counts = {cls: len(idx) for cls, idx in class_pixel_indices.items()}
    if any(count == 0 for count in class_counts.values()):
        class_counts = {cls: count for cls, count in class_counts.items() if count > 0}

    allocation = _proportional_allocation(class_counts, total_samples, min_per_class)

    all_rows, all_cols, all_labels = [], [], []
    for cls, n_to_sample in allocation.items():
        pixel_indices = class_pixel_indices[cls]
        chosen = rng.choice(len(pixel_indices), size=n_to_sample, replace=False)
        selected = pixel_indices[chosen]
        all_rows.append(selected[:, 0])
        all_cols.append(selected[:, 1])
        all_labels.append(np.full(n_to_sample, cls))

    return SampleSet(
        rows=np.concatenate(all_rows),
        cols=np.concatenate(all_cols),
        labels=np.concatenate(all_labels),
    )


def simple_random_sample(
    strata: np.ndarray,
    total_samples: int = DEFAULT_TOTAL_SAMPLES,
    random_seed: int = 12345,
    valid_mask: np.ndarray | None = None,
) -> SampleSet:
    """Simple (non-stratified) random sampling — Doc 0's alternate method."""
    strata = np.asarray(strata)
    if valid_mask is not None:
        valid_mask = np.asarray(valid_mask, dtype=bool)
    else:
        valid_mask = np.ones(strata.shape, dtype=bool)

    rng = np.random.default_rng(random_seed)
    all_indices = np.argwhere(valid_mask)
    n_to_sample = min(total_samples, len(all_indices))
    chosen = rng.choice(len(all_indices), size=n_to_sample, replace=False)
    selected = all_indices[chosen]

    return SampleSet(
        rows=selected[:, 0],
        cols=selected[:, 1],
        labels=strata[selected[:, 0], selected[:, 1]],
    )


def train_test_split_stratified(
    samples: SampleSet,
    train_split: float = DEFAULT_TRAIN_SPLIT,
    random_seed: int = 12345,
) -> TrainTestSplit:
    """
    Split an existing SampleSet into train/test, preserving each
    class's proportion in both sets (Doc 0: 70% train / 30% test).
    """
    rng = np.random.default_rng(random_seed)

    train_idx, test_idx = [], []
    for cls in np.unique(samples.labels):
        cls_positions = np.where(samples.labels == cls)[0]
        rng.shuffle(cls_positions)
        n_train = max(1, int(round(len(cls_positions) * train_split)))
        train_idx.extend(cls_positions[:n_train])
        test_idx.extend(cls_positions[n_train:])

    train_idx = np.array(sorted(train_idx))
    test_idx = np.array(sorted(test_idx))

    train_set = SampleSet(rows=samples.rows[train_idx], cols=samples.cols[train_idx], labels=samples.labels[train_idx])
    test_set = SampleSet(rows=samples.rows[test_idx], cols=samples.cols[test_idx], labels=samples.labels[test_idx])

    return TrainTestSplit(train=train_set, test=test_set, train_split=train_split)
