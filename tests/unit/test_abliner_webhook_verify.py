"""Webhook verification (review row B3): hex HMAC-SHA256 over "<timestamp>.<raw body>", constant time on bytes,
±300 s. Placeholders only."""
import hashlib
import hmac

import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.services.abliner import webhooks

SECRET = "whsec_TEST_placeholder"
BODY = b'{"id":"evt_1","event":"transaction.completed","data":{"status":"completed"}}'
NOW = 1_790_000_000


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "abliner_webhook_secret", SecretStr(SECRET))


def _headers(body=BODY, ts=NOW, secret=SECRET, prefix=""):
    signature = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"x-webhook-timestamp": str(ts), "x-webhook-signature": prefix + signature}


def test_valid_signature_and_an_optional_prefix():
    webhooks.verify(BODY, _headers(), now=NOW)
    webhooks.verify(BODY, _headers(prefix="sha256="), now=NOW + 299)


@pytest.mark.parametrize("headers, body, code", [
    (_headers(secret="whsec_other"), BODY, "invalid_signature"),
    (_headers(), BODY + b" ", "invalid_signature"),
    ({**_headers(), "x-webhook-signature": ""}, BODY, "invalid_signature"),
    ({**_headers(), "x-webhook-signature": "é" * 64}, BODY, "invalid_signature"),
    ({**_headers(), "x-webhook-timestamp": "abc"}, BODY, "invalid_timestamp"),
    (_headers(ts=NOW - 301), BODY, "stale_timestamp"),
    (_headers(ts=NOW + 301), BODY, "stale_timestamp"),
])
def test_rejections(headers, body, code):
    with pytest.raises(webhooks.Rejected) as caught:
        webhooks.verify(body, headers, now=NOW)
    assert caught.value.code == code and caught.value.status == 401


def test_unconfigured_secret_and_oversized_bodies(monkeypatch):
    with pytest.raises(webhooks.Rejected) as caught:
        webhooks.verify(b"x" * (64 * 1024 + 1), _headers(), now=NOW)
    assert caught.value.status == 413
    monkeypatch.setattr(get_settings(), "abliner_webhook_secret", SecretStr(""))
    with pytest.raises(webhooks.Rejected) as caught:
        webhooks.verify(BODY, _headers(), now=NOW)
    assert (caught.value.status, caught.value.code) == (503, "webhook_not_configured")
