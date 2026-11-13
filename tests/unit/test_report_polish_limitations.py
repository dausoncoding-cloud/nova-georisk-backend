"""Report polish (12): near-binary Random Forest scores stated from the run."""
import pytest

from tests.unit._report_run import report_run, section as _section


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory)

# (12) Near-binary scores stated from the run; model and scores unchanged.
def test_score_distribution_is_recorded_and_stated_in_limitations(run):
    result, _, _, text, _, _ = run
    distribution = result.summary["products"]["flood_probability"]["score_distribution"]
    assert set(distribution) == {"exact_0_pct", "exact_1_pct", "between_pct", "valid_cells"}
    assert sum(distribution[k] for k in ("exact_0_pct", "exact_1_pct", "between_pct")) == pytest.approx(100)
    limitations = _section(text, "Limitations and what is not claimed", "Provenance summary")
    assert f"{distribution['exact_0_pct']:.1f}%" in limitations and f"{distribution['exact_1_pct']:.1f}%" in limitations
    assert "near-binary" in limitations and "SAR screening rule" in limitations and "tied" in limitations
