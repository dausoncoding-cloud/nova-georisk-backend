from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.gee import export as export_service


@patch("app.services.gee.export.requests")
def test_render_thumbnail_writes_response_bytes(mock_requests, tmp_path):
    image = MagicMock()
    aoi = MagicMock()
    image.getThumbURL.return_value = "https://example.com/thumb.png"

    mock_response = MagicMock()
    mock_response.content = b"fake-png-bytes"
    mock_requests.get.return_value = mock_response

    output_path = tmp_path / "sub" / "thumb.png"
    result = export_service.render_thumbnail(image, aoi, output_path, vis_params={"min": 0, "max": 1})

    image.getThumbURL.assert_called_once()
    call_args = image.getThumbURL.call_args[0][0]
    assert call_args["region"] == aoi
    assert call_args["min"] == 0
    assert call_args["max"] == 1
    assert call_args["format"] == "png"
    assert call_args["crs"] == "EPSG:4326"

    mock_requests.get.assert_called_once_with("https://example.com/thumb.png", timeout=export_service.DEFAULT_DOWNLOAD_TIMEOUT_SECONDS)
    mock_response.raise_for_status.assert_called_once()

    assert result == output_path
    assert output_path.read_bytes() == b"fake-png-bytes"


@patch("app.services.gee.export.requests")
def test_render_thumbnail_creates_parent_directories(mock_requests, tmp_path):
    image = MagicMock()
    mock_response = MagicMock()
    mock_response.content = b"data"
    mock_requests.get.return_value = mock_response

    deep_path = tmp_path / "a" / "b" / "c" / "out.png"
    assert not deep_path.parent.exists()

    export_service.render_thumbnail(image, MagicMock(), deep_path)

    assert deep_path.parent.exists()
    assert deep_path.exists()


@patch("app.services.gee.export.requests")
def test_render_thumbnail_raises_on_http_error(mock_requests, tmp_path):
    image = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("HTTP 429")
    mock_requests.get.return_value = mock_response

    with pytest.raises(Exception, match="HTTP 429"):
        export_service.render_thumbnail(image, MagicMock(), tmp_path / "out.png")


@patch("app.services.gee.export.requests")
def test_render_thumbnail_uses_custom_dimensions(mock_requests, tmp_path):
    image = MagicMock()
    mock_response = MagicMock()
    mock_response.content = b"data"
    mock_requests.get.return_value = mock_response

    export_service.render_thumbnail(image, MagicMock(), tmp_path / "out.png", dimensions=500)

    call_args = image.getThumbURL.call_args[0][0]
    assert call_args["dimensions"] == 500
