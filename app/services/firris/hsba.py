"""HSBA flood label (firris-science-3), pre-registered in the remediation plan §1.8a (2026-11-16).

Chini, Hostache, Giustarini & Matgen (2017), "A Hierarchical Split-Based Approach for Parametric
Thresholding of SAR Images: Flood Inundation as a Test Case", IEEE TGRS 55(12): 6975-6988,
doi:10.1109/TGRS.2017.2737664. Page numbers below are journal pages.

Runs locally (numpy/scipy) on the downloaded, admitted arrays. Every constant here is a pre-registered
value; none may be changed after seeing measurement results.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import ndimage
from scipy.optimize import curve_fit

METHOD = "HSBA (Chini et al. 2017, IEEE TGRS 55(12): 6975-6988)"
MIN_TILE_PX = 64                     # pre-registered minimum tile size (both dimensions)
MIN_ADMITTED_FRACTION = 0.5          # a tile is evaluated only if >= 50% of its pixels are admitted
ASHMAN_D_MIN = 2.0                   # C1, Eqs. 6-7, p. 6979
BHATTACHARYYA_MIN = 0.99             # C2, Eqs. 8-9, p. 6979
SURFACE_RATIO_MIN = 0.1              # C3, Eqs. 10-11, p. 6979
WATER_MEAN_MAX_DB = -15.0            # C4 (our deviation D-a), flood image only
BINS_MIN, BINS_MAX = 30, 200         # Freedman-Diaconis bins, clamped
SEED_RATIO = 0.1                     # y_seed: first y >= mu_w where G_nw(y) >= 0.1 * G_w(y)
TOLERANCE_GRID_DB = np.round(np.arange(0, 101) * 0.1, 1)          # 0.0 .. 10.0
CHANGE_GRID_DB = np.round(np.arange(-100, 1) * 0.1, 1)            # -10.0 .. 0.0
SLOPE_MAX_DEG = 15.0                 # deviation D-f: excluded before seeding and growth
JRC_EXCLUDE_PCT = 90.0               # deviation D-e: occurrence >= 90% set to 0 at the end
CONNECTIVITY = np.ones((3, 3), dtype=bool)  # 8-connected region growing
NO_DISTINCT_WATER_CLASS = "NO_DISTINCT_WATER_CLASS"

DEVIATIONS = (
    "C4: tile water-component mean of the VV flood image <= -15 dB (own physical check; replaces the patent mode ranges)",
    "Speckle filter: Earth Engine focal median, 50 m radius (paper: Gamma 5x5, p. 6981)",
    "Change sign: target minus baseline, flooding negative (paper: reference minus flood, p. 6983)",
    "Domain: admitted AOI pixels only (paper: whole image)",
    "JRC occurrence >= 90% excluded at the end, in addition to the paper's baseline-water step (p. 6984)",
    "Slope >= 15 degrees excluded before seeding and region growing (not in the paper)",
    "No accepted tile: NO_DISTINCT_WATER_CLASS, no threshold of any kind (not defined in the paper)",
)
LIMITATION = ("The HSBA label targets open water on bare soil and sparsely vegetated land; flooded vegetation and urban areas, "
              "where radar backscatter increases, are not detected (Chini et al. 2017, pp. 6982, 6985).")


def _gauss2(y, a1, m1, s1, a2, m2, s2):
    return a1 * np.exp(-(y - m1) ** 2 / (2 * s1 ** 2)) + a2 * np.exp(-(y - m2) ** 2 / (2 * s2 ** 2))


def _gauss(y, a, m, s):
    return a * np.exp(-(y - m) ** 2 / (2 * s ** 2))


def histogram_edges(values: np.ndarray) -> np.ndarray:
    """Freedman-Diaconis bin edges, clamped to 30-200 bins."""
    lo, hi = float(values.min()), float(values.max())
    if hi <= lo:
        hi = lo + 1e-6
    q75, q25 = np.percentile(values, [75, 25])
    iqr = q75 - q25
    if iqr > 0:
        width = 2 * iqr * len(values) ** (-1 / 3)
        bins = int(math.ceil((hi - lo) / width))
    else:
        bins = BINS_MIN
    bins = min(max(bins, BINS_MIN), BINS_MAX)
    return np.linspace(lo, hi, bins + 1)


def otsu_threshold(counts: np.ndarray, centers: np.ndarray) -> float:
    """Otsu (1979) on a histogram; used only for the LM initial guess (Eqs. 3-5)."""
    weights = counts.astype(float)
    total = weights.sum()
    cum_w = np.cumsum(weights)
    cum_mu = np.cumsum(weights * centers)
    w0 = cum_w[:-1]
    w1 = total - w0
    valid = (w0 > 0) & (w1 > 0)
    mu0 = np.divide(cum_mu[:-1], w0, out=np.zeros_like(w0), where=w0 > 0)
    mu1 = np.divide(cum_mu[-1] - cum_mu[:-1], w1, out=np.zeros_like(w1), where=w1 > 0)
    between = np.where(valid, w0 * w1 * (mu0 - mu1) ** 2, -1)
    index = int(np.argmax(between))
    return float((centers[index] + centers[index + 1]) / 2)


@dataclass
class TwoGaussianFit:
    low: tuple[float, float, float]    # (A, mean, sd) of the lower-mean component (water / change)
    high: tuple[float, float, float]   # (A, mean, sd) of the higher-mean component
    ashman_d: float
    bhattacharyya: float
    surface_ratio: float
    edges: np.ndarray = field(repr=False)
    counts: np.ndarray = field(repr=False)

    def passes(self) -> bool:
        return (self.ashman_d > ASHMAN_D_MIN and self.bhattacharyya > BHATTACHARYYA_MIN
                and self.surface_ratio > SURFACE_RATIO_MIN)

    def record(self) -> dict[str, Any]:
        return {"low": {"A": self.low[0], "mean_db": self.low[1], "sd_db": self.low[2]},
                "high": {"A": self.high[0], "mean_db": self.high[1], "sd_db": self.high[2]},
                "ashman_d": self.ashman_d, "bhattacharyya": self.bhattacharyya, "surface_ratio": self.surface_ratio,
                "bins": int(len(self.counts)),
                "c1": self.ashman_d > ASHMAN_D_MIN, "c2": self.bhattacharyya > BHATTACHARYYA_MIN,
                "c3": self.surface_ratio > SURFACE_RATIO_MIN}


def fit_two_gaussians(values: np.ndarray) -> TwoGaussianFit | None:
    """Two-Gaussian Levenberg-Marquardt fit (Eq. 2) with Otsu first guesses (Eqs. 3-5); None if it fails."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < 10:
        return None
    edges = histogram_edges(values)
    counts, _ = np.histogram(values, bins=edges)
    centers = (edges[:-1] + edges[1:]) / 2
    width = float(edges[1] - edges[0])
    threshold = otsu_threshold(counts, centers)
    below, above = values[values <= threshold], values[values > threshold]
    if below.size < 2 or above.size < 2:
        return None
    guesses = []
    for part in (below, above):
        mean = float(part.mean())
        sd = max(float(part.std()), width)
        amplitude = float(counts[min(max(np.searchsorted(edges, mean, side="right") - 1, 0), len(counts) - 1)])
        guesses += [max(amplitude, 1.0), mean, sd]
    try:
        params, _ = curve_fit(_gauss2, centers, counts.astype(float), p0=guesses, method="lm", maxfev=5000)
    except (RuntimeError, ValueError, FloatingPointError):
        return None
    if not np.all(np.isfinite(params)):
        return None
    a1, m1, s1, a2, m2, s2 = params
    s1, s2 = abs(s1), abs(s2)
    if s1 == 0 or s2 == 0 or a1 <= 0 or a2 <= 0:
        return None
    low, high = sorted([(float(a1), float(m1), float(s1)), (float(a2), float(m2), float(s2))], key=lambda c: c[1])
    fitted = np.clip(_gauss2(centers, *low, *high), 0, None)
    p, q = counts / counts.sum(), fitted / fitted.sum() if fitted.sum() > 0 else fitted
    bhattacharyya = float(np.sum(np.sqrt(p * q)))                                   # Eq. 8
    ashman_d = float(math.sqrt(2) * abs(high[1] - low[1]) / math.sqrt(low[2] ** 2 + high[2] ** 2))  # Eq. 6
    areas = (low[0] * low[2], high[0] * high[2])                                    # sqrt(2*pi) cancels, Eq. 10
    surface_ratio = float(min(areas) / max(areas))
    return TwoGaussianFit(low, high, ashman_d, bhattacharyya, surface_ratio, edges, counts)


def quadrants(r0: int, c0: int, rows: int, cols: int) -> list[tuple[int, int, int, int]]:
    """Four near-equal, non-overlapping quadrants (row0, col0, rows, cols) of a tile (Eq. 1, p. 6978)."""
    rh, cw = rows // 2, cols // 2
    return [(r0, c0, rh, cw), (r0, c0 + cw, rh, cols - cw), (r0 + rh, c0, rows - rh, cw), (r0 + rh, c0 + cw, rows - rh, cols - cw)]


def splittable(rows: int, cols: int, min_tile: int = MIN_TILE_PX) -> bool:
    """A tile is split only if every child is still at least min_tile in both dimensions."""
    return rows // 2 >= min_tile and cols // 2 >= min_tile


@dataclass
class HSBAResult:
    status: str                       # "labelled" or NO_DISTINCT_WATER_CLASS
    label: np.ndarray
    diagnostics: dict[str, Any]


def _select_tiles(xf, xc, admitted, min_tile):
    height, width = xf.shape
    bimodal = np.zeros(xf.shape, dtype=bool)
    records = []
    queue = [(0, 0, 0, height, width)]
    while queue:
        level, r0, c0, rows, cols = queue.pop(0)
        record = {"level": level, "row": r0, "col": c0, "rows": rows, "cols": cols, "evaluated": False, "accepted": False}
        accepted = False
        if rows >= min_tile and cols >= min_tile:
            window = (slice(r0, r0 + rows), slice(c0, c0 + cols))
            mask = admitted[window]
            record["admitted_fraction"] = float(mask.mean())
            if record["admitted_fraction"] >= MIN_ADMITTED_FRACTION:
                record["evaluated"] = True
                flood_fit, change_fit = fit_two_gaussians(xf[window][mask]), fit_two_gaussians(xc[window][mask])
                record["flood_image"] = flood_fit.record() if flood_fit else None
                record["change_image"] = change_fit.record() if change_fit else None
                c4 = bool(flood_fit and flood_fit.low[1] <= WATER_MEAN_MAX_DB)
                record["c4"] = c4
                accepted = bool(flood_fit and change_fit and flood_fit.passes() and change_fit.passes() and c4)
        record["accepted"] = accepted
        records.append(record)
        if accepted:
            bimodal[r0:r0 + rows, c0:c0 + cols] = True   # descendants are not considered (Algorithm 1)
        elif splittable(rows, cols, min_tile):
            queue.extend((level + 1, *child) for child in quadrants(r0, c0, rows, cols))
    return bimodal & admitted, records


def seed_threshold(fit: TwoGaussianFit) -> float | None:
    """y_seed: first histogram value >= mu_w where the fitted non-water curve reaches 10% of the water curve."""
    centers = (fit.edges[:-1] + fit.edges[1:]) / 2
    for y in centers[centers >= fit.low[1]]:
        if _gauss(y, *fit.high) >= SEED_RATIO * _gauss(y, *fit.low):
            return float(y)
    return None


def grow(image: np.ndarray, domain: np.ndarray, seeds: np.ndarray, limit: float) -> np.ndarray:
    """8-connected region growing: pixels <= limit inside the domain that are connected to a seed."""
    candidates = domain & (image <= limit)
    labels, _ = ndimage.label(candidates | seeds, structure=CONNECTIVITY)
    keep = np.unique(labels[seeds])
    keep = keep[keep > 0]
    return np.isin(labels, keep)


def optimise(xf, xc, domain, seeds, bimodal, y_seed, fit: TwoGaussianFit):
    """Joint grid search of tolerance and change threshold minimising RMSE(G_w, flood histogram in BM) (p. 6984)."""
    edges, centers = fit.edges, (fit.edges[:-1] + fit.edges[1:]) / 2
    target = _gauss(centers, *fit.low)
    nbins = len(centers)
    seed_hist, _ = np.histogram(xf[seeds & bimodal], bins=edges)
    rmse = np.full((len(TOLERANCE_GRID_DB), len(CHANGE_GRID_DB)), np.inf)
    for i, tolerance in enumerate(TOLERANCE_GRID_DB):
        added = grow(xf, domain, seeds, y_seed + tolerance) & ~seeds & bimodal
        values, changes = xf[added], xc[added]
        inside = (values >= edges[0]) & (values <= edges[-1])
        bins = np.clip(np.searchsorted(edges, values[inside], side="right") - 1, 0, nbins - 1)
        steps = np.searchsorted(CHANGE_GRID_DB, changes[inside], side="left")   # change <= grid[k] for k >= step
        keep = steps < len(CHANGE_GRID_DB)
        table = np.zeros((nbins, len(CHANGE_GRID_DB)))
        np.add.at(table, (bins[keep], steps[keep]), 1)
        hist = seed_hist[:, None] + np.cumsum(table, axis=1)
        rmse[i] = np.sqrt(np.mean((hist - target[:, None]) ** 2, axis=0))
    i, k = np.unravel_index(int(np.argmin(rmse)), rmse.shape)   # first minimum: smallest tolerance, then lowest threshold
    return float(TOLERANCE_GRID_DB[i]), float(CHANGE_GRID_DB[k]), float(rmse[i, k])


def derive_hsba_label(*, flood_db: np.ndarray, baseline_db: np.ndarray, slope_deg: np.ndarray, jrc_occurrence: np.ndarray,
                      valid_mask: np.ndarray, min_tile: int = MIN_TILE_PX) -> HSBAResult:
    started = time.monotonic()
    xf = np.asarray(flood_db, dtype=float)
    xr = np.asarray(baseline_db, dtype=float)
    xc = xf - xr                                       # deviation D-c: target - baseline, flooding negative
    admitted = np.asarray(valid_mask, dtype=bool) & np.isfinite(xf) & np.isfinite(xr)
    domain = admitted & np.isfinite(slope_deg) & (np.asarray(slope_deg, dtype=float) < SLOPE_MAX_DEG)
    bimodal, tiles = _select_tiles(xf, xc, admitted, min_tile)
    diagnostics: dict[str, Any] = {
        "method": METHOD, "label_rule_version": "hsba-1", "parameters": {
            "min_tile_px": min_tile, "min_admitted_fraction": MIN_ADMITTED_FRACTION, "ashman_d_min": ASHMAN_D_MIN,
            "bhattacharyya_min": BHATTACHARYYA_MIN, "surface_ratio_min": SURFACE_RATIO_MIN,
            "water_mean_max_db": WATER_MEAN_MAX_DB, "bins": f"Freedman-Diaconis, clamped {BINS_MIN}-{BINS_MAX}",
            "seed_ratio": SEED_RATIO, "tolerance_grid_db": [0.0, 10.0, 0.1], "change_grid_db": [-10.0, 0.0, 0.1],
            "connectivity": 8, "slope_max_deg": SLOPE_MAX_DEG, "jrc_exclude_pct": JRC_EXCLUDE_PCT},
        "deviations": list(DEVIATIONS), "limitation": LIMITATION,
        "tiles_examined": sum(1 for t in tiles if t["evaluated"]), "tiles_accepted": sum(1 for t in tiles if t["accepted"]),
        "tiles": tiles, "bimodal_mask_pixels": int(bimodal.sum()), "admitted_pixels": int(admitted.sum()),
    }

    def fallback(reason: str) -> HSBAResult:
        diagnostics.update(status=NO_DISTINCT_WATER_CLASS, reason=reason, runtime_s=round(time.monotonic() - started, 2))
        return HSBAResult(NO_DISTINCT_WATER_CLASS, np.zeros(xf.shape, dtype=np.uint8), diagnostics)

    if not bimodal.any():
        return fallback("No tile shows separate water and non-water populations in both the flood and the change image.")
    water_fit, change_fit = fit_two_gaussians(xf[bimodal]), fit_two_gaussians(xc[bimodal])
    if water_fit is None or change_fit is None:
        return fallback("The pooled two-Gaussian refit over the accepted tiles failed.")
    diagnostics["pooled_fit"] = {"flood_image": water_fit.record(), "change_image": change_fit.record()}
    y_seed = seed_threshold(water_fit)
    if y_seed is None:
        return fallback("No seed threshold: the fitted non-water curve never reaches 10% of the water curve.")
    seeds = domain & (xf <= y_seed)
    tolerance, change_threshold, rmse = optimise(xf, xc, domain, seeds, bimodal, y_seed, water_fit)
    grown = grow(xf, domain, seeds, y_seed + tolerance)
    flood = seeds | (grown & ~seeds & (xc <= change_threshold))
    seeds_reference = domain & (xr <= y_seed)
    baseline_water = grow(xr, domain, seeds_reference, y_seed + tolerance) if seeds_reference.any() else np.zeros_like(flood)
    jrc = np.asarray(jrc_occurrence, dtype=float)
    permanent = np.isfinite(jrc) & (jrc >= JRC_EXCLUDE_PCT)
    label = flood & ~baseline_water & ~permanent & admitted
    diagnostics.update(
        status="labelled", reason=None,
        thresholds={"seed_db": y_seed, "region_growing_limit_db": y_seed + tolerance, "tolerance_db": tolerance,
                    "change_threshold_db": change_threshold, "rmse": rmse},
        pixel_counts={"seeds": int(seeds.sum()), "grown": int(grown.sum()), "flood_before_exclusions": int(flood.sum()),
                      "baseline_water_removed": int((flood & baseline_water).sum()),
                      "jrc_removed": int((flood & ~baseline_water & permanent).sum()), "label": int(label.sum())},
        runtime_s=round(time.monotonic() - started, 2))
    return HSBAResult("labelled", label.astype(np.uint8), diagnostics)


def rule_text(diagnostics: dict[str, Any]) -> str:
    """One-sentence description of the label actually derived, for the report and reference basis."""
    if diagnostics.get("status") != "labelled":
        return f"{METHOD}: no distinct water class ({diagnostics.get('reason')})"
    t = diagnostics["thresholds"]
    return (f"{METHOD}: {diagnostics['tiles_accepted']} of {diagnostics['tiles_examined']} tiles accepted (C1 Ashman's D > 2, "
            f"C2 Bhattacharyya > 0.99, C3 surface ratio > 0.1 in both the VV flood and the change image; C4 water mean <= -15 dB); "
            f"seeds VV <= {t['seed_db']:.2f} dB, region growing to {t['region_growing_limit_db']:.2f} dB, grown pixels kept if the "
            f"change is <= {t['change_threshold_db']:.1f} dB; baseline water, slope >= 15 deg and JRC occurrence >= 90% excluded")
