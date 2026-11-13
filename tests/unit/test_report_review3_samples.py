"""Client review 3: sample point sets are named for what they hold and listed under audit, not GIS data."""
import zipfile

import pytest

from app.api.v1.serializers import deliverable_group
from tests.unit._report_run import report_run

FULL = "Model training and test sample points, with features, scores and predictions"
SLIM = "Model training and test sample points, label and split only (Shapefile)"


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory, organization_name="Deeteki tech company", sample_report=True)


def test_sample_point_sets_have_descriptive_labels(run):
    result = run[0]
    files = result.output_files
    assert files["samples_shapefile"]["label"] == SLIM
    assert files["samples_geojson"]["label"] == f"{FULL} (GeoJSON)"
    for key, suffix in (("samples_geojson_gpkg", "GeoPackage"), ("samples_geojson_kml", "KML"), ("samples_geojson_shapefile_zip", "Shapefile")):
        assert files[key]["label"] == f"{FULL} ({suffix})", key


def test_vector_format_labels_are_readable_for_every_layer(run):
    files = run[0].output_files
    assert files["flood_extent_vector_gpkg"]["label"] == "Flood-candidate extent (model-classified) vector (GeoPackage)"


def test_sample_point_sets_belong_to_audit_and_provenance(run):
    result, directory, _, text, _, _ = run
    for key, entry in result.output_files.items():
        if key.startswith("samples"):
            assert deliverable_group(key, entry) == "audit", key
    downloads = text[text.index("Appendix B: downloads"):]
    assert "sample points" not in downloads and "Georeferenced" not in downloads
    with zipfile.ZipFile(directory / result.output_files["report_package"]["path"]) as archive:
        readme = archive.read("README.txt").decode()
    audit = readme[readme.index("Audit and provenance"):]
    assert SLIM in audit and f"{FULL} (Shapefile)" in audit


def test_prepared_by_uses_the_organization_name(run):
    _, _, _, text, _, _ = run
    assert "Prepared by: Deeteki tech company" in text
