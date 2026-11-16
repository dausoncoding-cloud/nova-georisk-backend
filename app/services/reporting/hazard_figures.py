"""Modelled flood hazard graphs (Depth & Exposure module, plan items 1.3 and 1.4).

Report-ready, in the r5.3 figure style: the report font (DejaVu Sans), drawn at the report's 16 cm figure width so
they print 1:1, light grid, PNG at 300 dpi and SVG. Inputs are the hazard record (``modelled_hazard.hazard_record``);
nothing is recomputed except the closed-form probability curve 1 − (1 − 1/T)^n.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from app.services.firris.modelled_hazard import probability_at_least_once  # noqa: E402

matplotlib.rcParams["svg.fonttype"] = "none"
WIDTH_IN = 16 / 2.54
DPI = 300
STYLE = {"font.family": "DejaVu Sans", "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
         "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7.5, "axes.linewidth": 0.8}
GRID = "#e3e3e3"
INK = "#0072B2"      # Okabe–Ito blue
INK_2 = "#D55E00"    # Okabe–Ito vermillion
INK_3 = "#009E73"    # Okabe–Ito green
AREA = "#7a7a7a"


def _save(fig, stem: Path) -> dict[str, Path]:
    png, svg = stem.with_suffix(".png"), stem.with_suffix(".svg")
    fig.savefig(png, dpi=DPI, bbox_inches="tight")
    fig.savefig(svg, bbox_inches="tight")
    plt.close(fig)
    return {"png": png, "svg": svg}


def _rp_colours(count: int) -> list:
    """An ordered, colour-blind-safe sequence (cividis) for return periods, light to dark."""
    return [plt.get_cmap("cividis")(value) for value in np.linspace(0.12, 0.88, count)]


def depth_return_period_figure(record: dict[str, Any], stem: Path, *, title: str) -> dict[str, Path]:
    """Depth of the wet cells (median, mean, p90, maximum) against the return period, with the wet share of the AOI."""
    rows = [r for r in record.get("return_periods") or [] if r.get("wet_area_km2")]
    with plt.rc_context(STYLE):
        fig, ax = plt.subplots(figsize=(WIDTH_IN, 3.6), layout="constrained")
        ax.set_title(title)
        ax.grid(True, color=GRID, linewidth=0.5, which="both")
        ax.set_axisbelow(True)
        if not rows:
            ax.set_xticks([])
            ax.set_yticks([])
            ax.text(0.5, 0.5, "No modelled flooding in this area\n" + (record.get("reason") or ""), ha="center", va="center",
                    transform=ax.transAxes)
            return _save(fig, stem)
        periods = [r["return_period_years"] for r in rows]
        series = (("max", "Maximum", INK_2, "^", (0, (1, 1.5))), ("p90", "90th percentile", INK_2, "s", "-"),
                  ("mean", "Mean", INK, "D", (0, (4, 2))), ("p50", "Median", INK, "o", "-"))
        for key, label, colour, marker, style in series:
            ax.plot(periods, [r["depth_m"][key] for r in rows], color=colour, marker=marker, markersize=4, linestyle=style,
                    linewidth=1.5, label=f"{label} depth of wet cells")
        ax.set_xscale("log")
        ax.set_xticks(periods)
        ax.set_xticklabels([str(p) for p in periods])
        ax.minorticks_off()
        ax.set_xlabel("Return period of the river discharge, T (years; log scale)")
        ax.set_ylabel("Modelled flood depth (m)")
        ax.set_ylim(0, max(r["depth_m"]["max"] for r in rows) * 1.12)
        share = ax.twinx()
        share.bar(periods, [r["wet_pct_of_aoi"] for r in rows], width=[p * 0.18 for p in periods], color=AREA, alpha=0.25,
                  label="Wet share of the area (right axis)", zorder=0)
        share.set_ylabel("Modelled wet share of the area (%)")
        share.set_ylim(0, max(100.0, max(r["wet_pct_of_aoi"] for r in rows) * 1.1))
        ax.set_zorder(share.get_zorder() + 1)
        ax.patch.set_visible(False)
        handles = ax.get_legend_handles_labels()[0] + share.get_legend_handles_labels()[0]
        labels = ax.get_legend_handles_labels()[1] + share.get_legend_handles_labels()[1]
        fig.legend(handles, labels, loc="outside lower center", ncol=3, frameon=False)
        return _save(fig, stem)


def aep_figure(record: dict[str, Any], stem: Path, *, title: str, years_max: int = 100) -> dict[str, Path]:
    """Left: AEP against the return period (AEP = 1/T). Right: P(at least one occurrence in n years) for each T."""
    rows = (record.get("occurrence") or {}).get("rows") or []
    periods = [r["return_period_years"] for r in rows]
    with plt.rc_context(STYLE):
        fig, (left, right) = plt.subplots(1, 2, figsize=(WIDTH_IN, 3.7), layout="constrained")
        fig.suptitle(title, fontsize=8.5)
        for ax in (left, right):
            ax.grid(True, color=GRID, linewidth=0.5, which="both")
            ax.set_axisbelow(True)
        t = np.logspace(np.log10(min(periods)), np.log10(max(periods)), 200)
        left.plot(t, 100 / t, color=INK, linewidth=1.5)
        left.plot(periods, [r["aep"] * 100 for r in rows], "o", color=INK, markersize=4)
        for period, row in zip(periods, rows):
            left.annotate(f"{row['aep'] * 100:.3g}%", (period, row["aep"] * 100), textcoords="offset points", xytext=(4, 3),
                          fontsize=6.5)
        left.set_xscale("log")
        left.set_yscale("log")
        left.set_xticks(periods)
        left.set_xticklabels([str(p) for p in periods])
        left.minorticks_off()
        left.set_yticks([0.2, 0.5, 1, 2, 5, 10])
        left.set_yticklabels(["0.2", "0.5", "1", "2", "5", "10"])
        left.set_xlabel("Return period, T (years)")
        left.set_ylabel("Annual exceedance probability, AEP = 1/T (%)")
        left.set_title("AEP of the T-year river discharge")
        n = np.arange(1, years_max + 1)
        for colour, period in zip(_rp_colours(len(periods)), periods):
            right.plot(n, [probability_at_least_once(period, k) * 100 for k in n], color=colour, linewidth=1.5, label=f"T = {period}")
        right.axvline(30, color=AREA, linewidth=0.8, linestyle=(0, (4, 3)))
        p100 = probability_at_least_once(100, 30) * 100 if 100 in periods else None
        if p100 is not None:
            right.plot([30], [p100], "o", color=_rp_colours(len(periods))[periods.index(100)], markersize=4)
            right.annotate(f"T = 100, n = 30: {p100:.1f}%", (30, p100), textcoords="offset points", xytext=(6, -12), fontsize=6.5,
                           bbox={"boxstyle": "round,pad=0.2", "facecolor": "white", "edgecolor": "none", "alpha": 0.9})
        right.set_xlim(1, years_max)
        right.set_ylim(0, 100)
        right.set_xlabel("Number of years, n")
        right.set_ylabel("Probability of at least one occurrence (%)")
        right.set_title("P = 1 − (1 − 1/T)ⁿ (independent years)")
        fig.legend(*right.get_legend_handles_labels(), loc="outside lower center", ncol=len(periods), frameon=False,
                   title="Return period (years)", title_fontsize=7)
        return _save(fig, stem)
