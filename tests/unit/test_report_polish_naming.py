"""F3 naming on every client surface, and decision codes written out in words. Synthetic data proves behaviour only."""
import re
import zipfile

import pytest

from app.platform.engines.firris import FIRRISEngineAdapter, satellite_display_label
from tests.unit._report_run import report_run, section

NAME = "Flood-candidate extent (model-classified)"
BARE = re.compile(r"\bflood extent\b", re.IGNORECASE)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory)


def test_satellite_flood_extent_has_one_qualified_name():
    assert satellite_display_label("flood_extent", "random_forest") == NAME
    products = {p["key"]: p for p in FIRRISEngineAdapter().contract()["products"]}
    assert products["flood_extent"]["label"] == NAME  # the analysis form shows this label


def test_report_never_uses_bare_flood_extent(run):
    _, _, _, text, _, docx_text = run
    for body in (text, docx_text):
        assert not BARE.search(body), BARE.search(body).group(0)
    assert NAME in text


def test_download_labels_and_map_titles_use_the_qualified_name(run):
    result, directory, _, _, _, _ = run
    for key, entry in result.output_files.items():
        assert not BARE.search(str(entry.get("label", ""))), (key, entry.get("label"))
    for key in ("flood_extent_geotiff", "flood_extent_cog", "flood_extent_preview", "flood_extent_vector", "flood_extent_map_png"):
        assert result.output_files[key]["label"].startswith(NAME), key
    assert result.output_files["flood_extent_map_png"]["gis_metadata"]["cartography"]["title"] == NAME
    with zipfile.ZipFile(directory / result.output_files["flood_extent_gis_layer"]["path"]) as archive:
        readme = archive.read("README.txt").decode()
    assert NAME in readme and not BARE.search(readme)
