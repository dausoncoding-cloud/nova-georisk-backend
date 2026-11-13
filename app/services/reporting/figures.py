"""Publication figures for accuracy scopes (plan items 2.2/2.4), rendered headless with matplotlib.

Each figure is written as PNG (300 dpi) and SVG. Inputs are the accuracy-scope dictionaries
built by app.services.validation.accuracy_tables; no value is recomputed or adjusted here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless; the container also sets MPLBACKEND=Agg

import matplotlib.pyplot as plt  # noqa: E402

matplotlib.rcParams["svg.fonttype"] = "none"  # keep figure text as searchable, accessible SVG text

DPI = 300
LINE = "#1f4e79"
REFERENCE = "#7a7a7a"


def _fmt(value, digits=3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _save(fig, stem: Path) -> dict[str, Path]:
    png, svg = stem.with_suffix(".png"), stem.with_suffix(".svg")
    fig.savefig(png, dpi=DPI, bbox_inches="tight")
    fig.savefig(svg, bbox_inches="tight")
    plt.close(fig)
    return {"png": png, "svg": svg}


def roc_figure(scope: dict[str, Any], stem: Path) -> dict[str, Path]:
    points = [(p["fpr"], p["tpr"]) for p in scope["roc"] if p["fpr"] is not None and p["tpr"] is not None]
    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    ax.plot([0, 1], [0, 1], linestyle="--", color=REFERENCE, linewidth=1, label="chance (1:1)")
    ax.plot([x for x, _ in points], [y for _, y in points], color=LINE, linewidth=2, label="classifier")
    counts = scope["n_per_reference_class"]
    ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="False positive rate", ylabel="True positive rate", aspect="equal")
    ax.set_title(f"ROC — AUC {_fmt(scope['roc_auc'])}; n = {scope['n']:,} "
                 f"(positives {counts.get('1', 0):,}, negatives {counts.get('0', 0):,})", fontsize=8)
    ax.legend(loc="lower right", fontsize=7, frameon=False)
    return _save(fig, stem)


def pr_figure(scope: dict[str, Any], stem: Path) -> dict[str, Path]:
    points = [(p["recall"], p["precision"]) for p in scope["pr"] if p["recall"] is not None and p["precision"] is not None]
    prevalence = scope["prevalence"] or 0.0
    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    ax.axhline(prevalence, linestyle="--", color=REFERENCE, linewidth=1, label=f"chance (prevalence {prevalence:.3f})")
    ax.plot([x for x, _ in points], [y for _, y in points], color=LINE, linewidth=2, label="classifier")
    ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="Recall", ylabel="Precision", aspect="equal")
    ax.set_title(f"Precision–recall — AP {_fmt(scope['average_precision'])}; n = {scope['n']:,}", fontsize=8)
    ax.legend(loc="lower left", fontsize=7, frameon=False)
    return _save(fig, stem)


def confusion_text_color(value: int, peak: int) -> str:
    return "white" if value / peak > 0.5 else "black"


def confusion_figure(scope: dict[str, Any], stem: Path) -> dict[str, Path]:
    matrix = scope["confusion_matrix"]["classified"]
    cells = [[matrix["1"]["reference_1"], matrix["1"]["reference_0"]], [matrix["0"]["reference_1"], matrix["0"]["reference_0"]]]
    fig, ax = plt.subplots(figsize=(4.2, 3.6))
    ax.imshow(cells, cmap="Blues", vmin=0)
    peak = max(max(row) for row in cells) or 1
    for row in range(2):
        for col in range(2):
            # White text on dark cells keeps every count readable.
            ax.text(col, row, f"{cells[row][col]:,}", ha="center", va="center", fontsize=10,
                    color=confusion_text_color(cells[row][col], peak))
    ax.set_xticks([0, 1], ["Reference:\nflood candidate", "Reference:\nnot flood candidate"], fontsize=7)
    ax.set_yticks([0, 1], ["Classified:\nflood candidate", "Classified:\nnot flood candidate"], fontsize=7)
    ax.set_title(f"Confusion matrix; n = {scope['n']:,}", fontsize=8)
    return _save(fig, stem)


def class_metrics_figure(scope: dict[str, Any], stem: Path) -> dict[str, Path]:
    rows = scope["per_class"]
    labels = [row["class_name"] for row in rows]
    series = {"User's accuracy": [row["users_accuracy_pct"] for row in rows],
              "Producer's accuracy": [row["producers_accuracy_pct"] for row in rows],
              "F1 × 100": [None if row["f1_score"] is None else row["f1_score"] * 100 for row in rows]}
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    width = 0.25
    for index, (name, values) in enumerate(series.items()):
        positions = [i + (index - 1) * width for i in range(len(labels))]
        ax.bar(positions, [0 if v is None else v for v in values], width, label=name)
    ax.set_xticks(range(len(labels)), labels, fontsize=7)
    ax.set(ylim=(0, 100), ylabel="%")
    ax.set_title(f"Per-class accuracy; n = {scope['n']:,}", fontsize=8)
    ax.legend(fontsize=7, frameon=False, loc="lower right")
    return _save(fig, stem)


FIGURES = {"roc": roc_figure, "pr": pr_figure, "confusion": confusion_figure, "class_metrics": class_metrics_figure}


def scope_figures(directory: Path, scope: dict[str, Any]) -> dict[str, dict[str, Path]]:
    return {kind: render(scope, directory / f"figure-{scope['scope']}-{kind}") for kind, render in FIGURES.items()}
