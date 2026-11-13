"""Client review 2: internal agreement moves to Appendix A."""
import pytest

from tests.unit._report_run import report_run, section


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory, organization_name="Example Consulting Ltd", sample_report=True)


# Internal agreement moves to Appendix A; section 9 keeps one sentence.
def test_internal_agreement_is_one_sentence_in_section_9_and_detailed_in_appendix_a(run):
    result, _, _, text, _, _ = run
    accuracy = section(text, "9. Accuracy assessment", "10. Limitations")
    assert "Internal agreement with SAR screening labels —" not in accuracy and "Held-out sample" not in accuracy
    internal = next(s for s in result.summary["validation_dashboard"]["accuracy_assessment"]["scopes"] if s["scope"] == "internal_screening")
    sentence = next(s for s in accuracy.split(". ") if "held-out" in s)
    assert f"{internal['overall_accuracy_pct']:.1f}%" in sentence and "trained to reproduce" in sentence and "not map accuracy" in sentence
    appendix = section(text, "Appendix A", "Appendix B: downloads")
    assert "Confusion matrix" in appendix and "Held-out sample" in appendix
