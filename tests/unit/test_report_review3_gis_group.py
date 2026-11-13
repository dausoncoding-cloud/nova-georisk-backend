"""Client review 3: GIS data holds map layers only; model point sets are audit and provenance."""
import zipfile

import pytest

from app.api.v1.serializers import deliverable_group
from tests.unit._report_run import report_run

POINT_SETS = ("samples", "independent_reference_points", "validation_holdout_points")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory)


def test_gis_data_contains_map_layers_only(run):
    result = run[0]
    gis = {key: entry for key, entry in result.output_files.items() if deliverable_group(key, entry) == "gis_data"}
    assert gis, "expected map layers in GIS data"
    map_products = {"flood_extent", "flood_probability"}
    for key, entry in gis.items():
        assert entry.get("product_key") in map_products, (key, entry.get("product_key"))
        assert not key.startswith(POINT_SETS), key


def test_every_model_point_set_format_is_audit_and_provenance(run):
    result = run[0]
    point_sets = {key: entry for key, entry in result.output_files.items() if key.startswith(POINT_SETS)}
    assert {"independent_reference_points_gpkg", "validation_holdout_points_shapefile_zip"} <= set(point_sets)
    for key, entry in point_sets.items():
        assert deliverable_group(key, entry) == "audit", key


def test_report_and_readme_follow_the_grouping(run):
    result, directory, _, text, _, _ = run
    downloads = text[text.index("Appendix B: downloads"):]
    assert "Independent reference audit sample" not in downloads and "Validation hold-out points" not in downloads
    with zipfile.ZipFile(directory / result.output_files["report_package"]["path"]) as archive:
        readme = archive.read("README.txt").decode()
    gis = readme[readme.index("GIS data"):readme.index("Audit and provenance")]
    audit = readme[readme.index("Audit and provenance"):]
    for name in ("Independent reference audit sample (GeoPackage)", "Validation hold-out points (Shapefile)"):
        assert name not in gis and name in audit, name
