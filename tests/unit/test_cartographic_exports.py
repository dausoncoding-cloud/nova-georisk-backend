"""Cartographic delivery uses the protected GIS artifact, never a fabricated basemap."""
from __future__ import annotations

import json
import zipfile

import numpy as np
import pytest
from PIL import Image
from rasterio.warp import transform_bounds

from app.platform.result_exports import artifact_entry, build_result_exports
from app.services.maps.cartography import build_cartographic_exports
from app.services.maps.export import RasterSpec, write_cog


def _product(tmp_path):
    bounds = transform_bounds("EPSG:4326", "EPSG:3857", 36, -2, 37, -1)
    source = tmp_path / "flood_hazard_zonation.cog.tif"
    write_cog(str(source), np.asarray([[1, 2], [4, 5]], dtype="float32"),
              RasterSpec.from_bbox(*bounds, 2, 2, crs_epsg=3857), nodata=-9999.0)
    metadata = {
        "crs": "EPSG:3857", "bounds": list(bounds), "nodata": -9999.0,
        "units": "relative class", "vertical_datum": "reviewed-MSL",
        "producer": "Reviewed test producer",
        "target_period": {"start": "2020-06-01", "end": "2020-06-30"},
        "aoi_bounds_wgs84": [36, -2, 37, -1],
        "zone_break_policy": "empirical AOI quintiles; not an absolute safety standard",
        "legend": [
            {"label": label, "color": color}
            for label, color in zip(
                ("Relative very low", "Relative low", "Relative moderate",
                 "Relative high", "Relative very high"),
                ("#125A7C", "#50A58D", "#F2CE5B", "#E8873F", "#B33336"),
            )
        ],
    }
    entry = artifact_entry(source, label="Zonation", media_type="image/tiff",
                           artifact_type="raster", result_version=1, role="product",
                           product_key="flood_hazard_zonation", format_name="cog",
                           gis_metadata=metadata, layer={"renderable": True})
    return entry


def test_metadata_driven_map_pdf_png_are_protected_package_exports(tmp_path):
    entry = _product(tmp_path)
    output = build_result_exports(
        tmp_path, task_id="task-1", project_id="project-1", aoi_id="aoi-1",
        engine_key="firris", engine_version="1", result_type="flood_hazard_zonation",
        result_version=1, summary={"classification": "relative"},
        provenance={"source_bindings": {"hazard": {"dataset_id": "reviewed-source"}}},
        gis_metadata=entry["gis_metadata"], product_entries={"flood_hazard_zonation": entry},
    )
    png_entry = output["flood_hazard_zonation_map_png"]
    pdf_entry = output["flood_hazard_zonation_map_pdf"]
    assert pdf_entry["media_type"] == "application/pdf"
    assert (tmp_path / pdf_entry["path"]).read_bytes().startswith(b"%PDF")
    cartography = png_entry["gis_metadata"]["cartography"]
    # Client decisions D1/D5: map, neatline, frame coordinates and right-hand colour scale only.
    assert cartography["elements"] == ["map", "neatline", "coordinate_labels", "colour_scale"]
    for absent in ("scale_bar", "north_arrow", "locator", "graticule"):
        assert absent not in cartography
    assert png_entry["gis_metadata"]["vertical_datum"] == "reviewed-MSL"
    with Image.open(tmp_path / png_entry["path"]) as image:
        x0, y0, x1, y1 = cartography["map_box_px"]
        assert image.size == tuple(cartography["sheet_px"])
        assert image.getpixel((x0, (y0 + y1) // 2))[:3] == (0, 0, 0)  # neatline
        assert image.getpixel((10, 10))[:3] == (255, 255, 255)  # no title band
        embedded = json.loads(image.info["NOVA_GIS_METADATA"])
        assert embedded["source"]["crs"] == "EPSG:3857"
        assert embedded["source"]["zone_break_policy"].endswith("safety standard")
        assert embedded["cartography"]["source_artifact_sha256"] == entry["checksum_sha256"]
        assert embedded["cartography"]["colour_scale"]["kind"] == "class_key"
        assert [item["label"] for item in embedded["cartography"]["colour_scale"]["classes"]][:5] == [
            "Relative very low", "Relative low", "Relative moderate", "Relative high", "Relative very high"]
        assert all(label["text"].endswith((" m E", " m N")) for label in embedded["cartography"]["coordinate_labels"])
    with zipfile.ZipFile(tmp_path / output["report_package"]["path"]) as archive:
        assert f"reports/{png_entry['path']}" in archive.namelist()
        assert f"reports/{pdf_entry['path']}" in archive.namelist()
        report = json.loads(archive.read("result-metadata.json"))
        assert any(item["delivery_type"] == "map_pdf" for item in report["artifacts"])


def test_cartography_fails_closed_on_changed_source_checksum(tmp_path):
    entry = _product(tmp_path)
    entry["checksum_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum changed"):
        build_cartographic_exports(tmp_path, product_entries={"flood_hazard_zonation": entry},
                                   provenance={}, result_version=1)
