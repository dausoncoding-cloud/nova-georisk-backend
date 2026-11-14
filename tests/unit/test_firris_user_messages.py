"""Plan 4.2 (small part): only allow-listed FIRRISQualityError messages reach error_summary."""
from unittest.mock import MagicMock

import pytest

from app.services.firris.user_messages import GENERIC_FAILURE, public_error_summary
from app.services.gee.firris_pipeline import FIRRISQualityError
from app.services.gee.scene_qa import inspect_collection

AOI = {"type": "Polygon", "coordinates": [[[38.92, -7.99], [39.01, -7.99], [39.01, -7.9], [38.92, -7.9], [38.92, -7.99]]]}


def test_empty_sentinel1_window_names_its_dates():
    collection = MagicMock()
    collection.size.return_value.getInfo.return_value = 0
    with pytest.raises(ValueError) as caught:
        inspect_collection(collection, sensor="Sentinel-1", period={"start": "2024-05-21", "end": "2024-05-23"}, aoi=AOI, required_bands=["VV"])
    message = str(caught.value)
    assert message == "No Sentinel-1 scene over the area between 2024-05-21 and 2024-05-23 (end date exclusive)."
    assert public_error_summary(FIRRISQualityError(message)) == message


@pytest.mark.parametrize("message", [
    "The target and baseline windows must each contain Sentinel-1 passes from exactly one relative orbit, the same in both (target: 57; baseline: 130).",
    "Valid pixel coverage 41.20% is below the configured 70.00% threshold",
])
def test_allow_listed_quality_messages_are_shown(message):
    assert public_error_summary(FIRRISQualityError(message)) == message


@pytest.mark.parametrize("error", [
    FIRRISQualityError("Remote source metadata/export could not be verified; analysis inputs not released"),
    FIRRISQualityError("Required collection is empty or exceeds bounded per-scene QA limit"),
    FIRRISQualityError("No Sentinel-1 scene over the area between 2024-05-21 and 2024-05-23 (end date exclusive). /etc/secret"),
    ValueError("No Sentinel-1 scene over the area between 2024-05-21 and 2024-05-23 (end date exclusive)."),  # not a quality error
    RuntimeError("ee.EEException: Total request size (51340557 bytes) must be less than or equal to 50331648 bytes."),
])
def test_everything_else_keeps_the_generic_message(error):
    assert public_error_summary(error) == GENERIC_FAILURE
