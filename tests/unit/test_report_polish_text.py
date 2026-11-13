"""Report polish (1, 2, 5–9): client report wording, numbers and layout. Synthetic data proves behaviour only."""
import re

import pytest
from pypdf import PdfReader

from app.services.reporting.scientific_report import fraction_text, share_phrase
from tests.unit._report_run import report_run, section as _section

INTERNAL_WORDS = re.compile(r"\bbundle\b|remediation plan|not part of this release|client decision", re.IGNORECASE)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory)



def _independent(result):
    scopes = result.summary["validation_dashboard"]["accuracy_assessment"]["scopes"]
    return next(scope for scope in scopes if scope["scope"] == "independent_optical")


# (1) No empty sections and no internal project vocabulary.
def test_report_has_no_internal_vocabulary_or_empty_future_sections(run):
    _, _, _, text, docx, docx_text = run
    for body in (text, docx_text):
        assert not INTERNAL_WORDS.search(body), INTERNAL_WORDS.search(body).group(0)
    headings = [p.text for p in docx.paragraphs if p.style.name.startswith("Heading")]
    assert not any("Water delineation" in h or "Trend" in h for h in headings)
    scope = _section(text, "Scope of this report: not included in this version", "2. Study area")
    assert "Water delineation" in scope and "Trend analysis" in scope


# (2) Executive summary states the independent numbers and a plain reading.
def test_executive_summary_states_independent_accuracy_numbers(run):
    result, _, _, text, _, _ = run
    scope = _independent(result)
    flood = next(row for row in scope["per_class"] if row["class_label"] == "1")
    summary = _section(text, "1. Executive summary", "2. Study area")
    for expected in (f"n = {scope['n']:,}", f"overall accuracy {scope['overall_accuracy_pct']:.1f}%", f"kappa {scope['cohens_kappa']:.3f}",
                     f"F1 {scope['f1_flooded']:.3f}", f"user's accuracy {flood['users_accuracy_pct']:.1f}%",
                     f"producer's accuracy {flood['producers_accuracy_pct']:.1f}%"):
        assert expected in summary, expected
    assert f"the model detects {share_phrase(flood['producers_accuracy_pct'])} of the new open water seen by the optical reference" in summary


@pytest.mark.parametrize("pct, phrase", [(3, "very little"), (20, "less than a quarter"), (33, "about a third"), (46.5, "about half"),
                                         (55, "about half"), (66, "about two thirds"), (80, "most"), (97, "nearly all")])
def test_share_phrase(pct, phrase):
    assert share_phrase(pct) == phrase


# (5) The independent-reference sentence is stated once.
def test_independent_reference_sentence_is_not_repeated(run):
    _, _, _, text, _, _ = run
    section = _section(text, "Accuracy assessment against an independent Sentinel-2 optical reference", "Internal agreement with SAR")
    assert section.lower().count("census of n =") == 1
    accuracy = _section(text, "9. Accuracy assessment", "10. Limitations")
    assert accuracy.count("Accuracy assessment against an independent Sentinel-2 optical reference") == 1  # the heading only


# (6) Number formatting.
def test_fraction_text_uses_thousands_separators():
    assert fraction_text("2807/5736") == "2,807/5,736" and fraction_text("97127/100352") == "97,127/100,352"
    assert fraction_text(None) == "—"


def test_report_has_no_long_unformatted_numbers(run):
    _, _, _, text, _, docx_text = run
    for body in (text, docx_text):
        assert not re.search(r"\d+\.\d{6,}", body)
        assert not re.search(r"(?<![\d,./:-])\d{5,}(?![\d,])", body.replace("EPSG:4326", ""))


# (7) Sentences start with a capital letter.
def test_interval_note_is_a_capitalised_sentence(run):
    _, _, _, text, _, _ = run
    assert "census of all eligible pixels" not in text
    assert "Census of all eligible pixels" in text


# (8) Audit sample shown with the independent assessment.
def test_audit_sample_estimates_are_in_the_accuracy_section(run):
    result, _, _, text, _, _ = run
    weighted = result.summary["independent_accuracy"]["audit_sample"]["weighted_estimates"]
    section = _section(text, "Accuracy assessment against an independent Sentinel-2 optical reference", "Internal agreement with SAR")
    assert "Audit sample" in section and "area-weighted" in section
    assert f"{weighted['overall_accuracy_pct']:.1f}%" in section and "census metrics are the reported accuracy" in section


# (9) No page ends with a heading.
def test_no_page_ends_with_a_heading(run):
    _, _, pdf, _, docx, _ = run
    headings = {p.text for p in docx.paragraphs if p.style.name.startswith("Heading")}
    pages = PdfReader(pdf).pages
    for page in pages[:-1]:
        lines = [line.strip() for line in (page.extract_text() or "").splitlines() if line.strip()]
        assert lines and lines[-1] not in headings, lines[-1]


# Second visual review: the reference sentence says "not field-verified" once.
def test_independent_reference_says_not_field_verified_once(run):
    _, _, _, text, _, _ = run
    reference = _section(text, "Reference: Sentinel-2 optical flood reference", "Confusion matrix")
    assert reference.lower().count("not field-verified") == 1


# Second visual review: a table never splits from its caption or loses its last row to the next page.
def test_confusion_tables_stay_on_one_page(run):
    _, _, pdf, _, _, _ = run
    for page in PdfReader(pdf).pages:
        page_text = page.extract_text() or ""
        if "Confusion matrix (classified" in page_text:
            tail = page_text[page_text.index("Confusion matrix (classified"):]
            assert "Producer's accuracy" in tail


# Second visual review: both main maps fit on the page that starts the maps section.
def test_main_maps_share_one_page(run):
    _, _, pdf, _, _, _ = run
    page = next(p for p in PdfReader(pdf).pages if "7. Main maps" in (p.extract_text() or ""))
    assert len(page.images) == 2


# Second visual review: headline areas use thousands separators (large AOIs).
def test_headline_areas_use_thousands_separators(run):
    _, _, _, text, _, _ = run
    summary = _section(text, "1. Executive summary", "2. Study area")
    assert not re.search(r"\d{4,}\.\d{2} km²", summary)


# Decision codes are written out in words for the client.
def test_method_and_limitations_state_decisions_in_words(run):
    _, _, _, text, _, _ = run
    assert "client decision" not in text.lower()
    method = _section(text, "5. Method", "6. Quality gates")
    assert "degraded" in method and "per pixel" in method and "SCL class 1" in method
    limitations = _section(text, "Limitations and what is not claimed", "Provenance summary")
    assert "institutional data" in limitations


def test_scene_selection_text_states_the_recorded_thresholds():
    from app.services.reporting.scientific_report import scene_selection_text
    text = scene_selection_text({"max_cloud_pct": 20.0, "degraded_msi_max_pct": 0.1})
    assert "cloud cover ≤ 20%" in text and "degraded MSI ≤ 0.1%" in text and "masked per pixel" in text
    assert "degraded-MSI threshold not recorded" in scene_selection_text({"max_cloud_pct": 20.0})
