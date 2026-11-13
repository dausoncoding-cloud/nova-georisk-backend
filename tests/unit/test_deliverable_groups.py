"""2.5: every artifact is assigned a deliverable group at read time (legacy results included)."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api.v1.serializers import deliverable_group, serialize_result


@pytest.mark.parametrize("key,entry,group", [
    ("scientific_report_pdf", {"format": "pdf", "artifact_type": "report"}, "client_deliverable"),
    ("scientific_report_word", {"format": "docx", "artifact_type": "report"}, "client_deliverable"),
    ("flood_extent_map_png", {"delivery_type": "map_png", "artifact_type": "report"}, "client_deliverable"),
    ("flood_probability_map_pdf", {"delivery_type": "map_pdf", "artifact_type": "report"}, "client_deliverable"),
    ("firris_excel_report", {"delivery_type": "excel", "artifact_type": "report"}, "client_deliverable"),
    ("report_package", {"format": "zip", "artifact_type": "package"}, "client_deliverable"),
    ("flood_extent_cog", {"role": "product", "artifact_type": "raster"}, "gis_data"),
    ("flood_extent_vector", {"role": "product", "artifact_type": "vector"}, "gis_data"),
    ("flood_extent_gis_layer", {"delivery_type": "gis_layer_zip", "artifact_type": "report"}, "gis_data"),
    ("flood_extent_vector_gpkg", {"delivery_type": "gpkg", "artifact_type": "vector"}, "gis_data"),
    ("figure_independent_optical_roc_png", {"artifact_type": "report"}, "figures"),
    ("accuracy_internal_screening_confusion", {"artifact_type": "report"}, "figures"),
    ("complete_report_pdf", {"format": "pdf", "artifact_type": "report"}, "audit"),
    ("provenance", {"artifact_type": "report"}, "audit"),
    ("samples_csv", {"artifact_type": "report"}, "audit"),
    ("validation_holdout_points", {"artifact_type": "vector", "role": "export"}, "audit"),
])
def test_artifacts_are_grouped(key, entry, group):
    assert deliverable_group(key, entry) == group


def test_serializer_sets_the_group_on_products_and_exports_including_legacy_results():
    now = datetime.now(timezone.utc)
    files = {"flood_extent_cog": {"path": "a.tif", "role": "product", "artifact_type": "raster", "media_type": "image/tiff"},
             "flood_extent_map_pdf": {"path": "m.pdf", "role": "export", "artifact_type": "report", "delivery_type": "map_pdf", "media_type": "application/pdf"},
             "provenance": {"path": "p.json", "role": "export", "artifact_type": "report", "media_type": "application/json"}}
    result = SimpleNamespace(id=uuid.uuid4(), task_id=uuid.uuid4(), project_id=uuid.uuid4(), aoi_id=None, engine_key="firris",
                             result_type="flood_mapping", version=1, summary={}, output_files=files, provenance={}, created_at=now, updated_at=now)
    response = serialize_result(result)
    groups = {item.key: item.deliverable_group for item in [*response.products, *response.exports]}
    assert groups == {"flood_extent_cog": "gis_data", "flood_extent_map_pdf": "client_deliverable", "provenance": "audit"}
