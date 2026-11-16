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


# --- r5.3 multi-variable ROC figures (polished for the report, 2026-11-16) -------------------------------------
# One style for the combined chart and every panel: the report font (DejaVu Sans, as app.services.reporting.fonts),
# sizes chosen for print at the report's 16 cm figure width (drawn at that width, so 1:1), axes 0–1, square, light
# grid. Okabe–Ito colour-blind-safe palette; each curve keeps one colour in every figure (assigned by curve order).
ROC_WIDTH_IN = 16 / 2.54
ROC_STYLE = {"font.family": "DejaVu Sans", "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
             "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7.5, "axes.linewidth": 0.8}
ROC_X_LABEL = "False positive rate (1 − specificity)"
ROC_Y_LABEL = "True positive rate (sensitivity)"
RANDOM_COLOUR = "#7a7a7a"
GRID_COLOUR = "#e3e3e3"
MODEL_COLOUR = "#0072B2"  # Okabe–Ito blue
VARIABLE_COLOURS = ["#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#000000", "#F0E442"]


def _ordered_curves(record: dict[str, Any], model: str | None, order=None) -> list[dict[str, Any]]:
    """Model first, then ``order`` (or the record's order); unknown names keep their record order at the end."""
    names = list(order or record.get("order") or [])
    rank = {name: index for index, name in enumerate(names)}
    curves = list(record.get("curves") or [])
    return sorted(curves, key=lambda c: (c["name"] != model, rank.get(c["name"], len(rank)), curves.index(c)))


def roc_colours(record: dict[str, Any], model: str | None = None, order=None) -> dict[str, str]:
    """One colour per curve, the same in the combined chart and the panels."""
    colours, palette = {}, iter(VARIABLE_COLOURS)
    for curve in _ordered_curves(record, model, order):
        colours[curve["name"]] = MODEL_COLOUR if curve["name"] == model else next(palette, "#555555")
    return colours


def _roc_axes(ax, *, x_label: bool = True, y_label: bool = True) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.grid(True, color=GRID_COLOUR, linewidth=0.5)
    ax.set_axisbelow(True)
    if x_label:
        ax.set_xlabel(ROC_X_LABEL)
    if y_label:
        ax.set_ylabel(ROC_Y_LABEL)
    ax.plot([0, 1], [0, 1], linestyle=(0, (4, 3)), color=RANDOM_COLOUR, linewidth=0.9, zorder=2)


def _curve_xy(curve: dict[str, Any]) -> tuple[list[float], list[float]]:
    points = [(0.0, 0.0), *[(row["fpr"], row["tpr"]) for row in curve["table"]], (1.0, 1.0)]
    return [x for x, _ in points], [y for _, y in points]


def direction_text(curve: dict[str, Any], positive: str) -> str:
    return f"{curve['direction']} = {positive}"


def operating_point_text(op: dict[str, Any]) -> str:
    """'t = 0.50: TPR 0.465, FPR 0.029' (or the point's own label when it has no threshold)."""
    head = f"t = {op['threshold']:.2f}" if op.get("threshold") is not None else op.get("label", "Operating point")
    return f"{head}: TPR {op['tpr']:.3f}, FPR {op['fpr']:.3f}"


def _not_assessable_box(ax, reason: str | None, n: int | None = None, *, heading: str = "Not assessable", width: int = 30):
    reason = reason or "reason not recorded"
    text = heading + "\n" + textwrap.fill(reason[:1].upper() + reason[1:], width) + (f"\nn = {n:,}" if n is not None else "")
    ax.text(0.5, 0.5, text, ha="center", va="center", transform=ax.transAxes, fontsize=7,
            bbox={"boxstyle": "round", "facecolor": "white", "edgecolor": RANDOM_COLOUR}, zorder=6)


def multi_roc_figure(record: dict[str, Any], stem: Path, *, title: str, model: str | None = None,
                     note: str | None = None, positive: str = "positive", order=None) -> dict[str, Path]:
    """r5.3: one ROC per score against one reference, the 1:1 random-classifier line, each AUC in the legend.

    ``record`` is ``MultiRoc.record()`` (app.services.validation.multi_roc); nothing is recomputed here. The legend
    sits under the plot (it never covers a curve), ordered by AUC from high to low, entries "Variable (direction) —
    AUC 0.xxx"; the operating point of ``model`` and the random line follow, then each curve that is not assessable
    with its reason, then ``note``. When the record itself is not assessable, only the reason is shown.
    """
    from matplotlib.lines import Line2D

    with plt.rc_context(ROC_STYLE):
        if record.get("status") != "assessed":
            fig, ax = plt.subplots(figsize=(ROC_WIDTH_IN, ROC_WIDTH_IN * 0.8))
            _roc_axes(ax)
            ax.set_title(title)
            _not_assessable_box(ax, record.get("reason"), heading="Multi-variable ROC not assessable", width=44)
            return _save(fig, stem)
        colours = roc_colours(record, model, order)
        curves = _ordered_curves(record, model, order)
        assessed = sorted([c for c in curves if c["assessable"]], key=lambda c: -c["auc"])
        missing = [c for c in curves if not c["assessable"]]
        handles, labels = [], []
        for curve in assessed:
            is_model = curve["name"] == model
            handles.append(Line2D([], [], color=colours[curve["name"]], linewidth=2.4 if is_model else 1.6))
            labels.append(f"{curve['label']} ({direction_text(curve, positive)}) — AUC {curve['auc']:.3f}")
        op = next((c.get("operating_point") for c in assessed if c["name"] == model and c.get("operating_point")), None)
        if op and op.get("fpr") is not None:
            handles.append(Line2D([], [], marker="o", markersize=6, markerfacecolor="white", markeredgecolor=colours[model],
                                  markeredgewidth=1.8, linestyle="none"))
            labels.append(f"{next(c['label'] for c in assessed if c['name'] == model)} operating point, {operating_point_text(op)}")
        handles.append(Line2D([], [], color=RANDOM_COLOUR, linestyle=(0, (4, 3)), linewidth=0.9))
        labels.append("Random classifier (1:1) — AUC 0.500")
        extra = [f"Not assessable: {c['label']} — {c['reason']}" for c in missing] + ([note] if note else [])
        for line in extra:
            handles.append(Line2D([], [], linestyle="none"))
            labels.append(textwrap.fill(line, 100))
        rows = len(labels) + sum(label.count("\n") for label in labels)
        legend_in = 0.1 + 0.15 * rows
        plot_in = 4.5
        fig = plt.figure(figsize=(ROC_WIDTH_IN, plot_in + legend_in + 0.75), layout="constrained")
        grid = fig.add_gridspec(2, 1, height_ratios=[plot_in, legend_in])
        ax, legend_ax = fig.add_subplot(grid[0]), fig.add_subplot(grid[1])
        _roc_axes(ax)
        ax.set_title(f"{title}\nn = {record['n']:,} (positives {record['positives']:,}, negatives {record['negatives']:,})")
        for curve in reversed(assessed):  # the highest AUC drawn last, on top
            is_model = curve["name"] == model
            ax.plot(*_curve_xy(curve), color=colours[curve["name"]], linewidth=2.4 if is_model else 1.6,
                    zorder=4 if is_model else 3, clip_on=False, solid_joinstyle="round")
        if op and op.get("fpr") is not None:
            ax.plot([op["fpr"]], [op["tpr"]], marker="o", markersize=6, markerfacecolor="white",
                    markeredgecolor=colours[model], markeredgewidth=1.8, linestyle="none", zorder=5, clip_on=False)
        legend_ax.axis("off")
        legend_ax.legend(handles, labels, loc="upper center", frameon=False, handlelength=2.6, borderaxespad=0,
                         labelspacing=0.45)
        return _save(fig, stem)


def multi_roc_panels_figure(record: dict[str, Any], stem: Path, *, title: str, model: str | None = None,
                            positive: str = "positive", columns: int = 3, order=None) -> dict[str, Path]:
    """r5.3: the same curves as ``multi_roc_figure``, one panel per score (3 columns; 3×2 for six scores).

    Each panel: a title, its own curve in its own colour, the 1:1 random line, and the AUC with its direction and n
    inside the panel. The operating point is marked on the model panel only ("t = 0.50: TPR …, FPR …"). A panel
    that is not assessable gives the reason instead of a curve. Nothing is recomputed.
    """
    curves = _ordered_curves(record, model, order)
    if record.get("status") != "assessed" or not curves:
        return multi_roc_figure(record, stem, title=title, model=model, positive=positive, order=order)
    colours = roc_colours(record, model, order)
    rows = -(-len(curves) // columns)
    with plt.rc_context({**ROC_STYLE, "axes.titlesize": 8, "axes.labelsize": 7.5, "xtick.labelsize": 6.5,
                         "ytick.labelsize": 6.5}):
        fig, axes = plt.subplots(rows, columns, figsize=(ROC_WIDTH_IN, 0.55 + 2.55 * rows), squeeze=False, layout="constrained")
        for index, ax in enumerate(axes.flat):
            if index >= len(curves):
                ax.axis("off")
                continue
            curve = curves[index]
            is_model = curve["name"] == model
            _roc_axes(ax, x_label=index // columns == rows - 1 or index + columns >= len(curves), y_label=index % columns == 0)
            ax.set_title(textwrap.fill(curve["label"], 32))
            n = curve["positives"] + curve["negatives"]
            if not curve["assessable"]:
                _not_assessable_box(ax, curve["reason"], n, width=24)
                continue
            colour = colours[curve["name"]]
            ax.plot(*_curve_xy(curve), color=colour, linewidth=2.0 if is_model else 1.6, zorder=4, clip_on=False)
            ax.text(0.96, 0.04, f"AUC {curve['auc']:.3f}\n{direction_text(curve, positive)}\nn = {n:,}", ha="right",
                    va="bottom", fontsize=7, transform=ax.transAxes, zorder=6,
                    bbox={"boxstyle": "round", "facecolor": "white", "edgecolor": colour, "linewidth": 0.8})
            op = curve.get("operating_point")
            if is_model and op and op.get("fpr") is not None:
                ax.plot([op["fpr"]], [op["tpr"]], marker="o", markersize=5, markerfacecolor="white", markeredgecolor=colour,
                        markeredgewidth=1.5, linestyle="none", zorder=5, clip_on=False)
                ax.annotate(operating_point_text(op).replace(": ", ":\n", 1), xy=(op["fpr"], op["tpr"]),
                            xytext=(0.30, 0.42), textcoords="axes fraction", fontsize=6.5, ha="left", va="center",
                            arrowprops={"arrowstyle": "-", "color": colour, "linewidth": 0.7}, zorder=6,
                            bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "none", "alpha": 0.9})
        fig.suptitle(f"{title}\nn = {record['n']:,} (positives {record['positives']:,}, negatives {record['negatives']:,}); "
                     "dashed grey line: random classifier (AUC 0.500)", fontsize=8.5)
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
