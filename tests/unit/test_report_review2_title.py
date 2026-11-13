"""Client review 2: title page."""
from pypdf import PdfReader
import pytest

from tests.unit._report_run import report_run, section


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory, organization_name="Example Consulting Ltd", sample_report=True)


# Title page.
def test_title_page_shows_sample_report_and_prepared_by(run):
    _, _, pdf, _, _, _ = run
    first = PdfReader(pdf).pages[0].extract_text()
    title_block = first.split("1. Executive summary")[0]
    assert "Sample report" in title_block and "Prepared by: Example Consulting Ltd" in title_block
    assert "(demo)" not in title_block


def test_title_page_has_no_sample_or_prepared_by_when_not_given(tmp_path_factory):
    _, _, pdf, _, _, _ = report_run(tmp_path_factory)
    title_block = PdfReader(pdf).pages[0].extract_text().split("1. Executive summary")[0]
    assert "Sample report" not in title_block and "Prepared by" not in title_block
