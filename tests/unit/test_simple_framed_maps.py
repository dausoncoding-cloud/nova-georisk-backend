"""2.1 (client decisions D1 and D5): simple framed maps plus GIS-ready map layers.

The framed map carries only: the map at its true geometry, a neatline, coordinate labels on
the frame and a colour scale on the right. No title, north arrow, scale bar, inset or notes.
"""
import io
import json
import re
import zipfile

import numpy as np
import pytest
from PIL import Image
from pypdf import PdfReader
from rasterio.transform import from_origin

from app.platform.result_exports import artifact_entry
from app.services.maps.cartography import build_cartographic_exports
from app.services.maps.export import RasterSpec, write_cog

WEST, NORTH, RES = 36.0, -1.0, 0.002  # 300 x 120 cells -> 0.6 deg x 0.24 deg (aspect 2.5)
WIDTH, HEIGHT = 300, 120


def _raster(tmp_path, key, values, *, nodata, legend, units, renderable=True):
    path = tmp_path / f"{key}.cog.tif"
    write_cog(str(path), values, RasterSpec(transform=from_origin(WEST, NORTH, RES, RES), crs_epsg=4326), nodata=nodata)
    bounds = [WEST, NORTH - HEIGHT * RES, WEST + WIDTH * RES, NORTH]
    meta = {"crs": "EPSG:4326", "bounds": bounds, "nodata": nodata, "units": units, "legend": legend,
            "display_label": key.replace("_", " ").title(), "target_period": {"start": "2024-05-24", "end": "2024-05-26"}}
    return artifact_entry(path, label=key, media_type="image/tiff", artifact_type="raster", result_version=1, role="product",
                          product_key=key, format_name="cog", gis_metadata=meta, layer={"renderable": renderable})


def _extent(tmp_path):
    values = np.zeros((HEIGHT, WIDTH), dtype="uint8"); values[40:80, 100:200] = 1; values[:5, :5] = 255
    legend = {"entries": [{"label": "Not classified as flood candidate (0)", "color": "#228B22"},
                          {"label": "Model-classified flood candidate (1)", "color": "#00BFFF"}]}
    return _raster(tmp_path, "flood_extent", values, nodata=255, legend=legend, units="binary class")


def _score(tmp_path):
    values = np.tile(np.linspace(0.05, 0.95, WIDTH, dtype="float32"), (HEIGHT, 1)); values[:3, :3] = -9999.0
    legend = {"entries": [{"label": "0.00–0.20", "color": "#0B6E4F"}, {"label": "0.20–0.40", "color": "#F6D55C"},
                          {"label": "0.40–0.60", "color": "#ED553B"}, {"label": "0.60–1.00", "color": "#7A0019"}]}
    return _raster(tmp_path, "flood_probability", values, nodata=-9999.0, legend=legend, units="dimensionless")


def _build(tmp_path, *entries):
    products = {entry["product_key"]: entry for entry in entries}
    provenance = {"datasets": ["COPERNICUS/S1_GRD", "JRC/GSW1_4/GlobalSurfaceWater"], "science_version": "firris-science-2",
                  "target_period": {"start": "2024-05-24", "end": "2024-05-26"}, "baseline_period": {"start": "2022-08-28", "end": "2022-09-03"}}
    return build_cartographic_exports(tmp_path, product_entries=products, provenance=provenance, result_version=1)


def _layout(tmp_path, entry):
    with Image.open(tmp_path / entry["path"]) as image:
        return json.loads(image.info["NOVA_GIS_METADATA"])["cartography"], image.size, image.info.get("dpi")


def test_map_keeps_true_geometry_and_has_no_other_map_furniture(tmp_path):
    output = _build(tmp_path, _extent(tmp_path))
    layout, size, dpi = _layout(tmp_path, output["flood_extent_map_png"])
    x0, y0, x1, y1 = layout["map_box_px"]
    assert (x1 - x0) / (y1 - y0) == pytest.approx(WIDTH / HEIGHT, rel=0.01)
    assert dpi == pytest.approx((300, 300), abs=1)
    assert layout["elements"] == ["map", "neatline", "coordinate_labels", "colour_scale"]
    for absent in ("north_arrow", "scale_bar", "locator", "title_band", "notes"):
        assert absent not in layout
    assert layout["style"] == "simple framed map (client decision D5)"


def test_frame_coordinate_labels_lie_within_the_raster_bounds(tmp_path):
    output = _build(tmp_path, _extent(tmp_path))
    layout, _, _ = _layout(tmp_path, output["flood_extent_map_png"])
    lon = [label["value"] for label in layout["coordinate_labels"] if label["axis"] == "x"]
    lat = [label["value"] for label in layout["coordinate_labels"] if label["axis"] == "y"]
    assert len(lon) >= 2 and len(lat) >= 2
    assert all(WEST <= value <= WEST + WIDTH * RES for value in lon)
    assert all(NORTH - HEIGHT * RES <= value <= NORTH for value in lat)
    assert all(re.fullmatch(r"\d+(\.\d+)?°[EW]", label["text"]) for label in layout["coordinate_labels"] if label["axis"] == "x")


def test_classified_layer_gets_a_class_key_with_exactly_its_classes_and_no_data(tmp_path):
    output = _build(tmp_path, _extent(tmp_path))
    layout, _, _ = _layout(tmp_path, output["flood_extent_map_png"])
    scale = layout["colour_scale"]
    assert scale["kind"] == "class_key"
    assert [item["label"] for item in scale["classes"]] == ["Not classified as flood candidate (0)", "Model-classified flood candidate (1)", "No data"]


def test_continuous_layer_gets_a_gradient_bar_with_data_min_max_and_unit(tmp_path):
    output = _build(tmp_path, _score(tmp_path))
    layout, _, _ = _layout(tmp_path, output["flood_probability_map_png"])
    scale = layout["colour_scale"]
    assert scale["kind"] == "gradient"
    assert scale["min"] == pytest.approx(0.05, abs=1e-6) and scale["max"] == pytest.approx(0.95, abs=1e-6)
    assert scale["unit"] == "dimensionless" and scale["stops"] == ["#0B6E4F", "#F6D55C", "#ED553B", "#7A0019"]


def test_pdf_text_is_only_coordinates_and_colour_scale(tmp_path):
    output = _build(tmp_path, _extent(tmp_path), _score(tmp_path))
    layout, _, _ = _layout(tmp_path, output["flood_extent_map_png"])
    allowed = {label["text"] for label in layout["coordinate_labels"]} | {item["label"] for item in layout["colour_scale"]["classes"]}
    text = PdfReader(tmp_path / output["flood_extent_map_pdf"]["path"]).pages[0].extract_text()
    tokens = [line.strip() for line in text.splitlines() if line.strip()]
    assert tokens and all(token in allowed for token in tokens), tokens
    score_layout, _, _ = _layout(tmp_path, output["flood_probability_map_png"])
    score_text = PdfReader(tmp_path / output["flood_probability_map_pdf"]["path"]).pages[0].extract_text()
    score_allowed = {label["text"] for label in score_layout["coordinate_labels"]} | set(score_layout["colour_scale"]["labels"])
    assert all(line.strip() in score_allowed for line in score_text.splitlines() if line.strip())
    assert "Flood Probability" not in score_text and "North" not in score_text


def test_gis_layer_package_is_georeferenced_styled_and_credited(tmp_path):
    output = _build(tmp_path, _extent(tmp_path))
    entry = output["flood_extent_gis_layer"]
    assert entry["media_type"] == "application/zip"
    with zipfile.ZipFile(tmp_path / entry["path"]) as archive:
        names = set(archive.namelist())
        assert names == {"flood_extent.png", "flood_extent.pgw", "flood_extent.prj", "flood_extent.qml", "flood_extent.clr", "README.txt"}
        with Image.open(io.BytesIO(archive.read("flood_extent.png"))) as image:
            assert image.size == (WIDTH, HEIGHT) and image.mode == "RGBA"
            assert image.getpixel((0, 0))[3] == 0  # nodata is transparent
            palette = {pixel[:3] for pixel in image.getdata() if pixel[3]}
            assert palette == {(0x22, 0x8B, 0x22), (0x00, 0xBF, 0xFF)}  # no frame, text or legend pixels
        world = [float(line) for line in archive.read("flood_extent.pgw").decode().split()]
        assert world == pytest.approx([RES, 0, 0, -RES, WEST + RES / 2, NORTH - RES / 2])
        assert "WGS 84" in archive.read("flood_extent.prj").decode()
        qml = archive.read("flood_extent.qml").decode()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(qml)
        values = sorted(item.get("value") for item in root.iter("paletteEntry"))
        assert values == ["0", "1"]
        clr = archive.read("flood_extent.clr").decode().splitlines()
        assert clr == ["0 34 139 34", "1 0 191 255"]
        readme = archive.read("README.txt").decode()
        assert "Contains modified Copernicus Sentinel data" in readme and "JRC Global Surface Water" in readme
        assert "Target period: 2024-05-24 to 2024-05-26 (end-exclusive)" in readme
        assert "Baseline period: 2022-08-28 to 2022-09-03 (end-exclusive)" in readme


def test_non_renderable_products_are_not_mapped(tmp_path):
    entry = _extent(tmp_path); entry["layer"]["renderable"] = False
    assert _build(tmp_path, entry) == {}


@pytest.mark.parametrize("builder", [_extent, _score])
def test_every_label_fits_inside_the_sheet_and_no_large_empty_band(tmp_path, builder):
    from app.services.maps.cartography import _font
    entry = builder(tmp_path)
    output = _build(tmp_path, entry)
    layout, size, _ = _layout(tmp_path, output[f"{entry['product_key']}_map_png"])
    font = _font(34)
    x0, y0, x1, y1 = layout["map_box_px"]
    scale = layout["colour_scale"]
    texts = scale["labels"] if scale["kind"] == "gradient" else [item["label"] for item in scale["classes"]]
    panel_left = x1 + 70
    assert all(panel_left + 90 + font.getlength(text) <= size[0] for text in texts)
    assert size[1] - y1 <= 130  # sheet ends just below the frame labels
