"""Report polish (11): colour-bar title on the confidence map."""
import pytest

from tests.unit._report_run import report_run


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory)

# (11) Colour bar title.
def test_confidence_map_colour_bar_is_titled_model_confidence(run):
    result, _, _, _, _, _ = run
    scale = result.output_files["flood_probability_map_png"]["gis_metadata"]["cartography"]["colour_scale"]
    assert scale["labels"][-1] == "Model confidence (0–1)" and "dimensionless" not in scale["labels"]
    assert scale["unit"] == "dimensionless"  # layer metadata unchanged
