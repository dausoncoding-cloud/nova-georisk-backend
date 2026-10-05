import json
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.services.gee import atlas_orchestrator as orchestrator

AOI_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
}


@pytest.fixture()
def mocked_gee_stack():
    """
    Mocks every dependency the orchestrator calls out to, so the test
    verifies pure wiring logic: right number of layers, right generic
    file paths (not hardcoded to any one AOI), right manifest shape.
    """
    with patch("app.services.gee.atlas_orchestrator.auth_service") as mock_auth, \
         patch("app.services.gee.atlas_orchestrator.ingestion_service") as mock_ingestion, \
         patch("app.services.gee.atlas_orchestrator.pipeline") as mock_pipeline, \
         patch("app.services.gee.atlas_orchestrator.export_service") as mock_export:
        def _write_preview(_image, _aoi, output_path, **_kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (8, 6), color="blue").save(output_path)
            return output_path

        mock_export.render_thumbnail.side_effect = _write_preview
        yield {
            "auth": mock_auth,
            "ingestion": mock_ingestion,
            "pipeline": mock_pipeline,
            "export": mock_export,
        }


def test_generate_atlas_uses_generic_project_and_aoi_scoped_paths(mocked_gee_stack, tmp_path):
    manifest = orchestrator.generate_flood_screening_atlas(
        project_id="proj-123",
        aoi_id="aoi-456",
        aoi_geometry=AOI_GEOMETRY,
        target_start="2026-01-01",
        target_end="2026-01-31",
        baseline_start="2025-12-01",
        baseline_end="2025-12-31",
        output_root=tmp_path,
    )

    output_dir = tmp_path / "proj-123" / "aoi-456"
    assert output_dir.exists()
    # Not "ugalla" or any other hardcoded name anywhere in the output path.
    assert "ugalla" not in str(output_dir).lower()

    metadata_path = output_dir / "metadata.json"
    assert metadata_path.exists()
    saved = json.loads(metadata_path.read_text())
    assert saved["project_id"] == "proj-123"
    assert saved["aoi_id"] == "aoi-456"
    assert manifest.project_id == "proj-123"


def test_generate_atlas_initializes_gee_once(mocked_gee_stack, tmp_path):
    orchestrator.generate_flood_screening_atlas(
        project_id="p", aoi_id="a", aoi_geometry=AOI_GEOMETRY,
        target_start="2026-01-01", target_end="2026-01-31",
        baseline_start="2025-12-01", baseline_end="2025-12-31",
        output_root=tmp_path,
    )
    mocked_gee_stack["auth"].initialize_gee.assert_called_once()


def test_generate_atlas_produces_16_layers_with_urls(mocked_gee_stack, tmp_path):
    manifest = orchestrator.generate_flood_screening_atlas(
        project_id="p2", aoi_id="a2", aoi_geometry=AOI_GEOMETRY,
        target_start="2026-01-01", target_end="2026-01-31",
        baseline_start="2025-12-01", baseline_end="2025-12-31",
        output_root=tmp_path,
    )
    assert len(manifest.products) == 16
    for product in manifest.products:
        assert product["url"].startswith("/outputs/p2/a2/")
        assert {"key", "label", "url", "bounds", "crs", "width", "height", "legend"} <= set(product)
        assert product["bounds"] == [0.0, 0.0, 1.0, 1.0]
        assert product["crs"] == "EPSG:4326"
        assert (product["width"], product["height"]) == (8, 6)
    # Keys should be unique (no duplicate layers)
    keys = [p["key"] for p in manifest.products]
    assert len(keys) == len(set(keys))


def test_generate_atlas_reports_progress_from_0_to_100(mocked_gee_stack, tmp_path):
    progress_values = []
    orchestrator.generate_flood_screening_atlas(
        project_id="p3", aoi_id="a3", aoi_geometry=AOI_GEOMETRY,
        target_start="2026-01-01", target_end="2026-01-31",
        baseline_start="2025-12-01", baseline_end="2025-12-31",
        output_root=tmp_path,
        progress_callback=progress_values.append,
    )
    assert progress_values[-1] == 100
    assert progress_values == sorted(progress_values)  # monotonically increasing


def test_generate_atlas_includes_screening_caveat(mocked_gee_stack, tmp_path):
    manifest = orchestrator.generate_flood_screening_atlas(
        project_id="p4", aoi_id="a4", aoi_geometry=AOI_GEOMETRY,
        target_start="2026-01-01", target_end="2026-01-31",
        baseline_start="2025-12-01", baseline_end="2025-12-31",
        output_root=tmp_path,
    )
    assert "screening" in manifest.screening_caveat.lower()
    assert manifest.to_dict()["screening_caveat"] == manifest.screening_caveat


def test_generate_atlas_propagates_render_failure(mocked_gee_stack, tmp_path):
    mocked_gee_stack["export"].render_thumbnail.side_effect = RuntimeError("GEE quota exceeded")

    with pytest.raises(RuntimeError, match="GEE quota exceeded"):
        orchestrator.generate_flood_screening_atlas(
            project_id="p5", aoi_id="a5", aoi_geometry=AOI_GEOMETRY,
            target_start="2026-01-01", target_end="2026-01-31",
            baseline_start="2025-12-01", baseline_end="2025-12-31",
            output_root=tmp_path,
        )


def test_generate_atlas_works_for_two_different_aois_independently(mocked_gee_stack, tmp_path):
    """Proves this isn't hardcoded to one AOI — two different project/AOI pairs produce independent outputs."""
    orchestrator.generate_flood_screening_atlas(
        project_id="alpha", aoi_id="site-1", aoi_geometry=AOI_GEOMETRY,
        target_start="2026-01-01", target_end="2026-01-31",
        baseline_start="2025-12-01", baseline_end="2025-12-31",
        output_root=tmp_path,
    )
    orchestrator.generate_flood_screening_atlas(
        project_id="beta", aoi_id="site-2", aoi_geometry=AOI_GEOMETRY,
        target_start="2026-02-01", target_end="2026-02-28",
        baseline_start="2026-01-01", baseline_end="2026-01-31",
        output_root=tmp_path,
    )

    assert (tmp_path / "alpha" / "site-1" / "metadata.json").exists()
    assert (tmp_path / "beta" / "site-2" / "metadata.json").exists()


def test_generate_atlas_versions_outputs_by_result_id(mocked_gee_stack, tmp_path):
    manifest = orchestrator.generate_flood_screening_atlas(
        project_id="p", aoi_id="a", aoi_geometry=AOI_GEOMETRY,
        target_start="2026-01-01", target_end="2026-01-31",
        baseline_start="2025-12-01", baseline_end="2025-12-31",
        output_root=tmp_path, result_id="result-123", version=2,
    )
    assert (tmp_path / "p" / "a" / "result-123" / "metadata.json").exists()
    assert manifest.result_id == "result-123"
    assert manifest.version == 2
    assert all(item["url"].startswith("/api/v1/results/result-123/") for item in manifest.products)
