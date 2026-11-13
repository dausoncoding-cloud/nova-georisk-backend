"""Report polish (3, 10): figure legibility. Synthetic data proves behaviour only."""
import pytest

from app.services.reporting import figures


# (3) Curves that run along the axes stay visible.
def _capture(monkeypatch):
    captured = []
    monkeypatch.setattr(figures, "_save", lambda fig, stem: captured.append(fig) or {})
    return captured


def test_perfect_roc_and_pr_curves_are_drawn_above_the_frame(monkeypatch, tmp_path):
    captured = _capture(monkeypatch)
    figures.roc_figure({"roc": [{"fpr": 0, "tpr": 0}, {"fpr": 0, "tpr": 1}, {"fpr": 1, "tpr": 1}], "roc_auc": 1.0, "n": 10,
                        "n_per_reference_class": {"1": 5, "0": 5}}, tmp_path / "roc")
    figures.pr_figure({"pr": [{"recall": 0, "precision": 1}, {"recall": 1, "precision": 1}], "prevalence": 0.5,
                       "average_precision": 1.0, "n": 10}, tmp_path / "pr")
    for fig in captured:
        ax = fig.axes[0]
        assert ax.get_xlim()[0] < 0 < 1 < ax.get_xlim()[1] and ax.get_ylim()[0] < 0 < 1 < ax.get_ylim()[1]
        classifier = next(line for line in ax.get_lines() if line.get_label() == "classifier")
        assert classifier.get_clip_on() is False and classifier.get_zorder() > ax.spines["top"].get_zorder()


# (10) The class-metrics legend does not cover any bar.
def test_class_metrics_legend_does_not_overlap_bars(monkeypatch, tmp_path):
    captured = _capture(monkeypatch)
    rows = [{"class_name": "Flood candidate", "users_accuracy_pct": 48.9, "producers_accuracy_pct": 46.5, "f1_score": 0.477},
            {"class_name": "Not flood candidate", "users_accuracy_pct": 96.8, "producers_accuracy_pct": 97.1, "f1_score": 0.969}]
    figures.class_metrics_figure({"per_class": rows, "n": 106088}, tmp_path / "metrics")
    fig = captured[0]
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    ax = fig.axes[0]
    legend = ax.get_legend().get_window_extent(renderer)
    assert not any(bar.get_window_extent(renderer).overlaps(legend) for bar in ax.patches)
