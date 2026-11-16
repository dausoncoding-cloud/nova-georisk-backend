"""r5.1: the submission and preflight request needs at least one product (schema-level, before any provider call)."""
import pytest
from pydantic import ValidationError

from app.schemas.analyses import AnalysisSubmitRequest

BASE = {
    "project_id": "11111111-1111-4111-8111-111111111111", "aoi_id": "22222222-2222-4222-8222-222222222222",
    "operation": "flood_mapping", "products": ["flood_extent"],
    "parameters": {"workflow": {"source": {"provider": "gee", "date_mode": "pre-post",
                                           "target_period": {"start": "2024-05-24", "end": "2024-05-26"},
                                           "baseline_period": {"start": "2022-08-28", "end": "2022-09-03"}}}},
    "gis_metadata": {"crs": "EPSG:4326", "bounding_box": {"west": 38.92, "south": -7.99, "east": 39.01, "north": -7.9},
                     "spatial_resolution": {"x": 30, "y": 30, "unit": "m"}, "acquisition_date": "2024-05-26", "producer": "NOVA GeoRisk"},
}


def test_one_product_is_accepted():
    assert AnalysisSubmitRequest.model_validate(BASE).products[0].value == "flood_extent"


def test_empty_product_list_is_refused():
    with pytest.raises(ValidationError) as caught:
        AnalysisSubmitRequest.model_validate({**BASE, "products": []})
    assert caught.value.errors()[0]["loc"] == ("products",)


def test_overlapping_windows_are_refused_with_the_rule_the_ui_explains():
    source = {**BASE["parameters"]["workflow"]["source"], "baseline_period": {"start": "2024-05-20", "end": "2024-05-25"}}
    with pytest.raises(ValidationError, match="Baseline must precede target without overlap"):
        AnalysisSubmitRequest.model_validate({**BASE, "parameters": {"workflow": {"source": source}}})
