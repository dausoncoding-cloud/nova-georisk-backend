"""Client review 2: downloads appendix and package README."""
import zipfile

import pytest

from tests.unit._report_run import report_run, section


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory, organization_name="Example Consulting Ltd", sample_report=True)


# Appendix B: client deliverables and GIS data only, plus the package README.
def test_downloads_appendix_has_two_groups_and_points_to_the_readme(run):
    _, _, _, text, _, _ = run
    downloads = text[text.index("Appendix B: downloads"):]
    assert "Client deliverables" in downloads and "GIS data" in downloads
    assert "Figures and accuracy tables" not in downloads and "Audit and provenance" not in downloads
    assert "README.txt" in downloads


def test_result_package_contains_a_readme_listing_every_file(run):
    result, directory, _, _, _, _ = run
    with zipfile.ZipFile(directory / result.output_files["report_package"]["path"]) as archive:
        names = archive.namelist()
        readme = archive.read("README.txt").decode()
    for name in names:
        if name != "README.txt":
            assert name in readme, name
    for group in ("Client deliverables", "GIS data", "Figures and accuracy tables", "Audit and provenance"):
        assert group in readme


def test_downloads_appendix_lists_every_vector_format_like_the_readme(run):
    _, _, _, _, docx, _ = run
    texts = [p.text for p in docx.paragraphs]
    for suffix in ("(GeoPackage)", "(KML)", "(Shapefile)"):
        assert f"• Flood-candidate extent (model-classified) vector {suffix}" in texts, suffix
