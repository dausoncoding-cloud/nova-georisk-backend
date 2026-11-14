"""Every character drawn on a framed map exists in the embedded font (no tofu such as '0⊠1')."""
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from app.services.maps import cartography
from app.services.reporting.fonts import font_path
from tests.unit._report_run import report_run


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return report_run(tmp_path_factory)


def test_map_font_is_the_bundled_dejavu_even_without_system_fonts(monkeypatch):
    monkeypatch.delenv("NOVA_MAP_FONT_PATH", raising=False)
    font = cartography._font(34)
    assert Path(font.path) == font_path() and font.path.endswith("DejaVuSans.ttf")
    assert Path(cartography._font(34, bold=True).path) == font_path(bold=True)


def test_every_map_label_glyph_exists_in_the_font(run):
    result, _, _, _, _, _ = run
    cmap = TTFont(str(font_path())).getBestCmap()
    texts = []
    for key in ("flood_extent_map_png", "flood_probability_map_png"):
        layout = result.output_files[key]["gis_metadata"]["cartography"]
        scale = layout["colour_scale"]
        texts += scale.get("labels") or [item["label"] for item in scale["classes"]]
        texts += [label["text"] for label in layout["coordinate_labels"]]
    assert any("–" in text for text in texts) and any("°" in text for text in texts)
    missing = sorted({char for text in texts for char in text if not char.isspace() and ord(char) not in cmap})
    assert not missing, missing
