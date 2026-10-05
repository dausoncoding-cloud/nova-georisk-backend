from unittest.mock import MagicMock, patch

import pytest

from app.services.gee import auth


@pytest.fixture(autouse=True)
def _reset_gee_init_state():
    auth.reset_initialization_state()
    yield
    auth.reset_initialization_state()


@patch("app.services.gee.auth.ee")
def test_initialize_gee_calls_service_account_credentials_and_initialize(mock_ee):
    mock_credentials = MagicMock()
    mock_ee.ServiceAccountCredentials.return_value = mock_credentials

    auth.initialize_gee(
        service_account_email="nova@project.iam.gserviceaccount.com",
        key_path="/secrets/key.json",
        project_id="nova-georisk",
    )

    mock_ee.ServiceAccountCredentials.assert_called_once_with(
        "nova@project.iam.gserviceaccount.com", "/secrets/key.json"
    )
    mock_ee.Initialize.assert_called_once_with(mock_credentials, project="nova-georisk")
    assert auth.is_initialized() is True


@patch("app.services.gee.auth.ee")
def test_initialize_gee_is_idempotent_within_process(mock_ee):
    auth.initialize_gee(service_account_email="a@b.com", key_path="/k.json")
    auth.initialize_gee(service_account_email="a@b.com", key_path="/k.json")

    # Second call should be a no-op — Initialize only called once.
    assert mock_ee.Initialize.call_count == 1


@patch("app.services.gee.auth.ee")
def test_initialize_gee_force_reinitializes(mock_ee):
    auth.initialize_gee(service_account_email="a@b.com", key_path="/k.json")
    auth.initialize_gee(service_account_email="a@b.com", key_path="/k.json", force=True)

    assert mock_ee.Initialize.call_count == 2


@patch("app.services.gee.auth.get_settings")
def test_initialize_gee_raises_without_credentials(mock_settings):
    # An explicit None means "use configured settings"; isolate this test from
    # local development credentials rather than changing production fallback.
    mock_settings.return_value.gee_service_account_email = ""
    mock_settings.return_value.gee_service_account_key_path = ""
    mock_settings.return_value.gee_project_id = ""
    with pytest.raises(ValueError, match="required"):
        auth.initialize_gee(service_account_email=None, key_path=None)
