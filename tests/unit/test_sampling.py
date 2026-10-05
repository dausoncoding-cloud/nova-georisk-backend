import numpy as np
import pytest

from app.services.gee.sampling import (
    simple_random_sample,
    stratified_random_sample,
    train_test_split_stratified,
)


def _synthetic_strata(shape=(100, 100), seed=0):
    """A raster with 3 classes in roughly 60/30/10 proportions."""
    rng = np.random.default_rng(seed)
    return rng.choice([0, 1, 2], size=shape, p=[0.6, 0.3, 0.1])


def test_stratified_sample_respects_min_per_class():
    strata = _synthetic_strata()
    sample = stratified_random_sample(strata, total_samples=500, min_per_class=30)
    counts = sample.per_class_counts()
    for cls, count in counts.items():
        assert count >= 30


def test_stratified_sample_proportional_allocation_roughly_matches_population():
    strata = _synthetic_strata(shape=(200, 200), seed=1)
    sample = stratified_random_sample(strata, total_samples=2000, min_per_class=30)
    counts = sample.per_class_counts()
    # Class 0 (~60% of pixels) should get noticeably more samples than class 2 (~10%)
    assert counts[0] > counts[2]


def test_stratified_sample_never_exceeds_available_pixels():
    # A tiny raster where class 2 only has a handful of pixels
    strata = np.zeros((10, 10), dtype=int)
    strata[0, 0] = 2  # only 1 pixel of class 2
    sample = stratified_random_sample(strata, total_samples=500, min_per_class=30)
    counts = sample.per_class_counts()
    assert counts[2] == 1  # can't sample more than exists


def test_stratified_sample_respects_valid_mask():
    strata = np.ones((10, 10), dtype=int)
    mask = np.zeros((10, 10), dtype=bool)
    mask[:5, :] = True  # only top half is valid
    sample = stratified_random_sample(strata, total_samples=20, min_per_class=1, valid_mask=mask)
    assert (sample.rows < 5).all()


def test_simple_random_sample_size_capped_by_available_pixels():
    strata = np.zeros((5, 5), dtype=int)  # 25 pixels total
    sample = simple_random_sample(strata, total_samples=1000)
    assert sample.n == 25


def test_simple_random_sample_is_reproducible_with_same_seed():
    strata = _synthetic_strata()
    s1 = simple_random_sample(strata, total_samples=100, random_seed=42)
    s2 = simple_random_sample(strata, total_samples=100, random_seed=42)
    np.testing.assert_array_equal(s1.rows, s2.rows)
    np.testing.assert_array_equal(s1.cols, s2.cols)


def test_train_test_split_preserves_class_proportions():
    strata = _synthetic_strata()
    sample = stratified_random_sample(strata, total_samples=1000, min_per_class=30)
    split = train_test_split_stratified(sample, train_split=0.7)

    assert split.train.n + split.test.n == sample.n
    train_counts = split.train.per_class_counts()
    test_counts = split.test.per_class_counts()

    for cls in sample.per_class_counts():
        total = train_counts.get(cls, 0) + test_counts.get(cls, 0)
        train_ratio = train_counts.get(cls, 0) / total
        assert 0.55 < train_ratio < 0.85  # roughly 70%, allowing for rounding on small classes


def test_train_test_split_no_overlap():
    strata = _synthetic_strata()
    sample = stratified_random_sample(strata, total_samples=300, min_per_class=30)
    split = train_test_split_stratified(sample)

    train_coords = set(zip(split.train.rows.tolist(), split.train.cols.tolist()))
    test_coords = set(zip(split.test.rows.tolist(), split.test.cols.tolist()))
    assert train_coords.isdisjoint(test_coords)
