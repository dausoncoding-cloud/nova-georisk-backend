"""
Classification bands and colour legends for Doc 2's 12 standard flood
map products. Two kinds of bands appear in the source document:

1. **Absolute physical-unit bands** — Depth (m), Velocity (m/s),
   Duration (days), Return Period (years) — Doc 2 gives explicit
   numeric breakpoints for these, reproduced exactly below.
2. **Qualitative 0-1 index bands** — Hazard, Probability, Exposure,
   Vulnerability, Risk, Susceptibility, Zonation — Doc 2 only gives
   label/colour descriptions for these (e.g. "Very Low = Dark Green"),
   with no numeric cutoffs, since the underlying index has no fixed
   universal scale. Where the index is already 0-1 bounded (as every
   FIRRIS composite index is), this module applies the same
   documented equal-interval convention used in
   `app.services.firas.classification`. Doc 2's Flood Risk and
   Zonation legends list 6 tiers (adding "Extreme") rather than the
   5 tiers FIRRIS's own FRI classification uses — that's a genuine
   difference between the two source documents, reproduced as-is
   rather than silently merged.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Band:
    upper_bound: float  # inclusive
    label: str
    color_hex: str


def classify(value: float, bands: list[Band]) -> Band:
    for band in bands:
        if value <= band.upper_bound:
            return band
    return bands[-1]


def color_for_label(label: str, bands: list[Band]) -> str:
    """Look up a band's color by its label — used for label sets computed
    outside classify() itself (e.g. classify_hazard_index's quantile-based
    labels), so the API can still return a consistent legend color."""
    for band in bands:
        if band.label == label:
            return band.color_hex
    return "#94A3B8"  # fallback slate-gray for an unrecognized label


# --- 1. Flood Extent Map — binary, no numeric bands (see flood_products.compute_flood_extent) ---
EXTENT_COLORS = {
    "flooded": "#00BFFF",       # Blue/Cyan
    "permanent_water": "#00008B",  # Dark Blue
    "non_flooded": "#228B22",   # Green
    "no_data": "#FFFFFF",       # White
}

# --- 2. Flood Depth Map (metres) ---
DEPTH_BANDS: list[Band] = [
    Band(0.3, "Very Shallow", "#ADD8E6"),   # Light Blue
    Band(1.0, "Moderate Depth", "#FFFF00"),  # Yellow
    Band(2.0, "Deep Water", "#FFA500"),      # Orange
    Band(float("inf"), "Extreme Depth", "#FF0000"),  # Red
]

# --- 3. Flood Velocity Map (m/s) ---
VELOCITY_BANDS: list[Band] = [
    Band(0.5, "Slow Flow", "#ADD8E6"),
    Band(1.5, "Moderate Flow", "#FFFF00"),
    Band(2.5, "Dangerous Flow", "#FFA500"),
    Band(float("inf"), "Extreme Flow", "#FF0000"),
]

# --- 4. Flood Hazard Map (Hazard Index = Depth x Velocity; no fixed
# universal scale in Doc 2, so classification is quantile-based — see
# flood_products.classify_hazard_index) ---
HAZARD_MAP_BANDS: list[Band] = [
    Band(0.20, "Very Low", "#006400"),
    Band(0.40, "Low", "#90EE90"),
    Band(0.60, "Moderate", "#FFFF00"),
    Band(0.80, "High", "#FFA500"),
    Band(1.01, "Very High", "#FF0000"),
]

# --- 5. Flood Inundation Probability Map (0-1 probability) ---
PROBABILITY_BANDS: list[Band] = [
    Band(0.20, "Very Low", "#228B22"),
    Band(0.40, "Low", "#FFFF00"),
    Band(0.60, "Moderate", "#FFA500"),
    Band(0.80, "High", "#FF0000"),
    Band(1.01, "Extreme", "#800080"),
]

# --- 6. Flood Duration Map (days) ---
DURATION_BANDS: list[Band] = [
    Band(1.0, "<1 day", "#ADD8E6"),
    Band(7.0, "1-7 days", "#FFFF00"),
    Band(30.0, "7-30 days", "#FFA500"),
    Band(float("inf"), ">30 days", "#FF0000"),
]

# --- 7. Flood Frequency / Return Period Map (years) ---
RETURN_PERIOD_BANDS: list[Band] = [
    Band(5.0, "Very Frequent Flooding", "#ADD8E6"),
    Band(10.0, "Frequent Flooding", "#0000FF"),
    Band(50.0, "Moderate Frequency", "#FFFF00"),
    Band(100.0, "Rare Flooding", "#FFA500"),
    Band(float("inf"), "Extreme / Very Rare Flooding", "#FF0000"),
]

# --- 8. Flood Exposure Map (population/asset density, 0-1 normalized) ---
EXPOSURE_DENSITY_BANDS: list[Band] = [
    Band(0.25, "Low", "#90EE90"),
    Band(0.50, "Moderate", "#FFFF00"),
    Band(0.75, "High", "#FFA500"),
    Band(1.01, "Very High", "#FF0000"),
]

# --- 9. Flood Vulnerability Map (0-1 FVI) ---
VULNERABILITY_MAP_BANDS: list[Band] = [
    Band(0.20, "Very Low", "#006400"),
    Band(0.40, "Low", "#90EE90"),
    Band(0.60, "Moderate", "#FFFF00"),
    Band(0.80, "High", "#FFA500"),
    Band(1.01, "Very High", "#FF0000"),
]

# --- 10. Flood Risk Map (0-1, Risk = Hazard x Exposure x Vulnerability; 6-tier per Doc 2) ---
RISK_MAP_BANDS: list[Band] = [
    Band(1 / 6, "Very Low", "#006400"),
    Band(2 / 6, "Low", "#228B22"),
    Band(3 / 6, "Moderate", "#FFFF00"),
    Band(4 / 6, "High", "#FFA500"),
    Band(5 / 6, "Very High", "#FF0000"),
    Band(1.01, "Extreme", "#800080"),
]

# --- 11. Flood Susceptibility Map (0-1) ---
SUSCEPTIBILITY_BANDS: list[Band] = [
    Band(0.20, "Very Low", "#006400"),
    Band(0.40, "Low", "#90EE90"),
    Band(0.60, "Moderate", "#FFFF00"),
    Band(0.80, "High", "#FFA500"),
    Band(1.01, "Very High", "#FF0000"),
]

# --- 12. Flood Hazard Zonation Map (0-1, 6-tier per Doc 2) ---
ZONATION_BANDS: list[Band] = [
    Band(1 / 6, "Very Low", "#006400"),
    Band(2 / 6, "Low", "#228B22"),
    Band(3 / 6, "Moderate", "#FFFF00"),
    Band(4 / 6, "High", "#FFA500"),
    Band(5 / 6, "Very High", "#FF0000"),
    Band(1.01, "Extreme", "#8B0000"),
]
