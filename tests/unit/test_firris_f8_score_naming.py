"""F8: the satellite classifier score is named as a model confidence score, never "Flood Probability".

The API key ``flood_probability`` is kept for compatibility; only client-facing text changes.
"""
import json

from pypdf import PdfReader

from app.platform.engines.firris import FIRRISEngineAdapter
from app.services.maps.cartography import build_cartographic_exports
from tests.unit.test_cartographic_exports import _product
from tests.unit.test_firris_f4_validation_rasters import _run_engine

MODEL_SCORE_LABEL = "Model confidence score (Random Forest vote fraction)"


def test_contract_names_satellite_score_as_model_confidence_and_keeps_key():
    products = {item["key"]: item for item in FIRRISEngineAdapter().contract()["products"]}
    assert "flood_probability" in products
    assert products["flood_probability"]["label"] == MODEL_SCORE_LABEL
    assert "Flood Probability" not in json.dumps(products["flood_probability"])


def test_satellite_run_uses_model_confidence_label_on_every_client_surface(tmp_path):
    result, _ = _run_engine(tmp_path)
    score_entries = {key: entry for key, entry in result.output_files.items() if entry.get("product_key") == "flood_probability"}
    assert score_entries
    for entry in score_entries.values():
        assert "Flood Probability" not in entry["label"]
        assert entry["label"].startswith(MODEL_SCORE_LABEL)
        metadata = entry.get("gis_metadata") or {}
        if entry.get("artifact_type") in {"raster", "preview"}:
            assert metadata["display_label"] == MODEL_SCORE_LABEL
            assert "not a probability of flooding" in metadata["semantics"]
    for path in tmp_path.rglob("*"):
        if path.suffix in {".json", ".geojson", ".csv"}:
            assert "Flood Probability" not in path.read_text(errors="ignore"), path.name
    report = tmp_path / "firris-analysis-report.pdf"
    if report.is_file():
        text = "".join(page.extract_text() or "" for page in PdfReader(report).pages)
        assert "Flood Probability" not in text


def test_non_default_algorithm_is_not_called_a_random_forest_vote_fraction():
    from app.platform.engines.firris import satellite_display_label
    assert satellite_display_label("flood_probability", "random_forest") == MODEL_SCORE_LABEL
    label = satellite_display_label("flood_probability", "xgboost")
    assert label.startswith("Model confidence score") and "Random Forest" not in label
    assert satellite_display_label("flood_extent", "random_forest") == "Flood Extent"


def test_cartographic_title_uses_display_label_not_product_key(tmp_path):
    entry = _product(tmp_path)
    entry["gis_metadata"]["display_label"] = MODEL_SCORE_LABEL
    output = build_cartographic_exports(tmp_path, product_entries={"flood_hazard_zonation": entry},
                                        provenance={}, result_version=1)
    png = output["flood_hazard_zonation_map_png"]
    assert png["gis_metadata"]["cartography"]["title"] == MODEL_SCORE_LABEL
    assert png["label"].startswith(MODEL_SCORE_LABEL)
    assert "Flood Probability" not in json.dumps(png)
