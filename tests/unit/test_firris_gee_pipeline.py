from unittest.mock import patch

import pytest

from app.services.gee import firris_pipeline


@patch("app.services.gee.firris_pipeline.auth.initialize_gee")
def test_gee_pipeline_rejects_unregistered_dataset_before_execution(mock_initialize, tmp_path):
    with pytest.raises(ValueError, match="Unsupported GEE datasets"):
        firris_pipeline.fetch_feature_stack(
            {
                "target_period": {"start": "2025-03-01", "end": "2025-04-01"},
                "baseline_period": {"start": "2024-03-01", "end": "2024-04-01"},
                "datasets": ["users/arbitrary/unreviewed-asset"],
            },
            {"type": "Polygon", "coordinates": [[[36, -2], [37, -2], [37, -1], [36, -2]]]},
            tmp_path,
        )
    mock_initialize.assert_not_called()


@patch("app.services.gee.firris_pipeline.auth.initialize_gee")
def test_gee_pipeline_requires_complete_firris_dataset_set(mock_initialize, tmp_path):
    with pytest.raises(ValueError, match="missing required datasets"):
        firris_pipeline.fetch_feature_stack(
            {
                "target_period": {"start": "2025-03-01", "end": "2025-04-01"},
                "baseline_period": {"start": "2024-03-01", "end": "2024-04-01"},
                "datasets": ["COPERNICUS/S1_GRD"],
            },
            {"type": "Polygon", "coordinates": [[[36, -2], [37, -2], [37, -1], [36, -2]]]},
            tmp_path,
        )
    mock_initialize.assert_not_called()


@pytest.mark.parametrize("safeguard", ["cloud_mask", "sar_speckle_filter", "normalize_projection", "clip_to_aoi"])
@patch("app.services.gee.firris_pipeline.auth.initialize_gee")
def test_gee_pipeline_rejects_disabled_required_preprocessing(mock_initialize, safeguard, tmp_path):
    with pytest.raises(ValueError, match="cannot disable required safeguards"):
        firris_pipeline.fetch_feature_stack(
            {
                "target_period": {"start": "2025-03-01", "end": "2025-04-01"},
                "baseline_period": {"start": "2024-03-01", "end": "2024-04-01"},
                "preprocessing": {safeguard: False},
            },
            {"type": "Polygon", "coordinates": [[[36, -2], [37, -2], [37, -1], [36, -2]]]},
            tmp_path,
        )
    mock_initialize.assert_not_called()
