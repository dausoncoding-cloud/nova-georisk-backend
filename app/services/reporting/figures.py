"""Publication figures for accuracy scopes (plan items 2.2/2.4), rendered headless with matplotlib.

Each figure is written as PNG (300 dpi) and SVG. Inputs are the accuracy-scope dictionaries
built by app.services.validation.accuracy_tables; no value is recomputed or adjusted here.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless; the container also sets MPLBACKEND=Agg

import matplotlib.pyplot as plt  # noqa: E402

from app.services.validation.accuracy_tables import reference_columns  # noqa: E402
from app.services.validation.auc_presentation import scope_auc  # noqa: E402

matplotlib.rcParams["svg.fonttype"] = "none"  # keep figure text as searchable, accessible SVG text

DPI = 300
LINE = "#1f4e79"
REFERENCE = "#7a7a7a"
# A small margin keeps curves that run along an axis (a perfect classifier) visible.
LIMITS = (-0.02, 1.02)


def _fmt(value, digits=3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _save(fig, stem: Path) -> dict[str, Path]:
    png, svg = stem.with_suffix(".png"), stem.with_suffix(".svg")
    fig.savefig(png, dpi=DPI, bbox_inches="tight")
    fig.savefig(svg, bbox_inches="tight")
    plt.close(fig)
    return {"png": png, "svg": svg}


def roc_figure(scope: dict[str, Any], stem: Path) -> dict[str, Path]:
    """ROC labelled by its reference (r5.2). When the AUC is not assessable, no curve is drawn, only the reason."""
    view = scope_auc(scope)
    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    ax.set(xlim=LIMITS, ylim=LIMITS, xlabel="False positive rate", ylabel="True positive rate", aspect="equal")
    ax.set_title(f"ROC — {view.label}\nn = {scope['n']:,} (positives {view.positives:,}, negatives {view.negatives:,})", fontsize=8)
    if not view.assessable:
        ax.text(0.5, 0.5, "AUC not assessable\n" + textwrap.fill(view.reason[:1].upper() + view.reason[1:], 38), ha="center", va="center", fontsize=8,
                transform=ax.transAxes, bbox={"boxstyle": "round", "facecolor": "white", "edgecolor": REFERENCE})
        return _save(fig, stem)
    points = [(p["fpr"], p["tpr"]) for p in scope["roc"] if p["fpr"] is not None and p["tpr"] is not None]
    ax.plot([0, 1], [0, 1], linestyle="--", color=REFERENCE, linewidth=1, label="chance (1:1)")
    ax.plot([x for x, _ in points], [y for _, y in points], color=LINE, linewidth=2, label="classifier", zorder=3, clip_on=False)
    interval = (f"95% CI {view.interval[0]:.3f}–{view.interval[1]:.3f}" if view.interval
                else textwrap.fill((view.interval_note or "")[:1].upper() + (view.interval_note or "")[1:], 30))
    # Below the chance line, where a useful classifier's curve never runs.
    if view.caveat:  # near-perfect internal agreement: say what it means where the number is
        interval += "\nSame-data labels: not map accuracy"
    ax.text(0.96, 0.24, f"AUC {view.value:.3f}\n{interval}", ha="right", va="bottom", fontsize=9, transform=ax.transAxes,
            bbox={"boxstyle": "round", "facecolor": "white", "edgecolor": LINE})
    ax.legend(loc="lower right", fontsize=7, frameon=False)
    return _save(fig, stem)


# Okabe–Ito colour-blind-safe palette for the per-variable curves; the model keeps the house blue.
VARIABLE_COLOURS = ["#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#000000"]


def multi_roc_figure(record: dict[str, Any], stem: Path, *, title: str, model: str | None = None,
                     note: str | None = None, positive: str = "positive") -> dict[str, Path]:
    """r5.3: one ROC per score against one reference, the 1:1 random-classifier line, each AUC in the legend.

    ``record`` is ``MultiRoc.record()`` (app.services.validation.multi_roc). ``model`` names the curve drawn as
    the combined model (thick line, operating point marked). Curves that are not assessable are listed under
    the legend with the reason; no curve is drawn for them. When the record itself is not assessable, only
    the reason is shown. ``positive`` names the positive class in the legend ("lower = flood").
    """
    fig, ax = plt.subplots(figsize=(6.4, 6.6))
    ax.set(xlim=LIMITS, ylim=LIMITS, xlabel="False positive rate", ylabel="True positive rate", aspect="equal")
    if record.get("status") != "assessed":
        ax.set_title(title, fontsize=9)
        reason = record.get("reason") or "not recorded"
        ax.text(0.5, 0.5, "Multi-variable ROC not assessable\n" + textwrap.fill(reason[:1].upper() + reason[1:], 44),
                ha="center", va="center", fontsize=8, transform=ax.transAxes,
                bbox={"boxstyle": "round", "facecolor": "white", "edgecolor": REFERENCE})
        return _save(fig, stem)
    ax.set_title(f"{title}\nn = {record['n']:,} (positives {record['positives']:,}, negatives {record['negatives']:,})", fontsize=9)
    ax.plot([0, 1], [0, 1], linestyle="--", color=REFERENCE, linewidth=1, label="Random classifier (AUC 0.500)")
    missing, colours = [], iter(VARIABLE_COLOURS)
    curves = sorted(record["curves"], key=lambda c: c["name"] != model)  # the model first
    for curve in curves:
        if not curve["assessable"]:
            missing.append(f"{curve['label']}: not assessable ({curve['reason']})")
            continue
        points = [(0.0, 0.0), *[(row["fpr"], row["tpr"]) for row in curve["table"]], (1.0, 1.0)]
        is_model = curve["name"] == model
        direction = "" if is_model else f", {curve['direction']} = {positive}"
        ax.plot([x for x, _ in points], [y for _, y in points], color=LINE if is_model else next(colours),
                linewidth=2.4 if is_model else 1.4, zorder=4 if is_model else 3, clip_on=False,
                label=f"{curve['label']}{direction} (AUC {curve['auc']:.3f})")
        op = curve.get("operating_point")
        if is_model and op and op.get("fpr") is not None:
            ax.plot([op["fpr"]], [op["tpr"]], marker="o", markersize=7, markerfacecolor="white", markeredgecolor=LINE,
                    markeredgewidth=2, linestyle="none", zorder=5,
                    label=f"{op['label']} (TPR {op['tpr']:.3f}, FPR {op['fpr']:.3f})")
    for line in [*missing, *([note] if note else [])]:  # text-only legend rows, so nothing overlaps
        ax.plot([], [], linestyle="none", label=textwrap.fill(line, 90))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.11), fontsize=7, frameon=False, ncol=1, handlelength=2.2)
    return _save(fig, stem)


def multi_roc_panels_figure(record: dict[str, Any], stem: Path, *, title: str, model: str | None = None,
                            positive: str = "positive", columns: int = 3) -> dict[str, Path]:
    """r5.3: the same curves as ``multi_roc_figure``, one panel per score (small multiples).

    Each panel: its own curve, the 1:1 random-classifier line, the AUC with its direction, and n. The operating
    point is shown on the model panel only. A panel that is not assessable shows the reason instead of a curve.
    No value is computed here: everything comes from ``MultiRoc.record()``.
    """
    curves = sorted(record.get("curves") or [], key=lambda c: c["name"] != model)  # the model first
    if record.get("status") != "assessed" or not curves:
        return multi_roc_figure(record, stem, title=title, model=model, positive=positive)
    rows = -(-len(curves) // columns)
    fig, axes = plt.subplots(rows, columns, figsize=(3.0 * columns, 3.25 * rows), squeeze=False)
    colours = iter(VARIABLE_COLOURS)
    for ax, curve in zip(axes.flat, curves):
        is_model = curve["name"] == model
        colour = LINE if is_model else next(colours)
        ax.set(xlim=LIMITS, ylim=LIMITS, aspect="equal")
        ax.set_xlabel("False positive rate", fontsize=7)
        ax.set_ylabel("True positive rate", fontsize=7)
        ax.tick_params(labelsize=6)
        ax.set_title(textwrap.fill(curve["label"], 34), fontsize=7.5)
        ax.plot([0, 1], [0, 1], linestyle="--", color=REFERENCE, linewidth=0.9)
        n = curve["positives"] + curve["negatives"]
        if not curve["assessable"]:
            reason = curve["reason"] or "reason not recorded"
            ax.text(0.5, 0.5, "Not assessable\n" + textwrap.fill(reason[:1].upper() + reason[1:], 26) + f"\nn = {n:,}",
                    ha="center", va="center", fontsize=6.5, transform=ax.transAxes,
                    bbox={"boxstyle": "round", "facecolor": "white", "edgecolor": REFERENCE})
            continue
        points = [(0.0, 0.0), *[(row["fpr"], row["tpr"]) for row in curve["table"]], (1.0, 1.0)]
        ax.plot([x for x, _ in points], [y for _, y in points], color=colour, linewidth=2 if is_model else 1.5, clip_on=False)
        direction = "model score, higher" if is_model else curve["direction"]
        text = f"AUC {curve['auc']:.3f}\n{direction} = {positive}\nn = {n:,}"
        op = curve.get("operating_point")
        if is_model and op and op.get("fpr") is not None:
            ax.plot([op["fpr"]], [op["tpr"]], marker="o", markersize=5, markerfacecolor="white", markeredgecolor=LINE,
                    markeredgewidth=1.5, linestyle="none", zorder=5)
            text += f"\ncircle = operating point\n(TPR {op['tpr']:.3f}, FPR {op['fpr']:.3f})"
        ax.text(0.97, 0.04, text, ha="right", va="bottom", fontsize=6.5, transform=ax.transAxes,
                bbox={"boxstyle": "round", "facecolor": "white", "edgecolor": colour, "linewidth": 0.8})
    for ax in list(axes.flat)[len(curves):]:
        ax.axis("off")
    fig.suptitle(f"{title}\nn = {record['n']:,} (positives {record['positives']:,}, negatives {record['negatives']:,}); "
                 "dashed line: random classifier (AUC 0.500)", fontsize=8.5)
    fig.tight_layout()
    return _save(fig, stem)


def pr_figure(scope: dict[str, Any], stem: Path) -> dict[str, Path]:
    points = [(p["recall"], p["precision"]) for p in scope["pr"] if p["recall"] is not None and p["precision"] is not None]
    prevalence = scope["prevalence"] or 0.0
    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    ax.axhline(prevalence, linestyle="--", color=REFERENCE, linewidth=1, label=f"chance (prevalence {prevalence:.3f})")
    ax.plot([x for x, _ in points], [y for _, y in points], color=LINE, linewidth=2, label="classifier", zorder=3, clip_on=False)
    ax.set(xlim=LIMITS, ylim=LIMITS, xlabel="Recall", ylabel="Precision", aspect="equal")
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
    ax.set_xticks([0, 1], [name.replace(": ", ":\n") for name in reference_columns(scope["scope"])], fontsize=7)
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
    # Legend below the axes so it never covers a bar.
    ax.legend(fontsize=7, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3)
    return _save(fig, stem)


FIGURES = {"roc": roc_figure, "pr": pr_figure, "confusion": confusion_figure, "class_metrics": class_metrics_figure}


def scope_figures(directory: Path, scope: dict[str, Any]) -> dict[str, dict[str, Path]]:
    return {kind: render(scope, directory / f"figure-{scope['scope']}-{kind}") for kind, render in FIGURES.items()}
