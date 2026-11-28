"""Abliner client (plan §2, §8): signed deposits, one attempt, error mapping, phones, and no secret anywhere.
Placeholders only: tsl_live_TEST / whsec_TEST are not real keys."""
import hashlib
import hmac
import json
import logging

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.services.abliner import phone as phones
from app.services.abliner.client import AblinerClient, AblinerError, sign
from app.services.abliner.errors import map_error

API_KEY = "tsl_live_TEST_placeholder_key"
SECRET = "whsec_TEST_placeholder_secret"


@pytest.fixture()
def configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "abliner_api_key", SecretStr(API_KEY))
    monkeypatch.setattr(settings, "abliner_webhook_secret", SecretStr(SECRET))
    monkeypatch.setattr(settings, "abliner_api_base_url", "https://abliner.test")


def _client(handler, calls):
    def record(request):
        calls.append(request)
        return handler(request)
    return AblinerClient(transport=httpx.MockTransport(record), clock=lambda: 1_790_000_000)


def test_deposit_is_signed_over_the_exact_bytes_sent(configured):
    calls = []
    client = _client(lambda request: httpx.Response(201, json={"status": "success", "data": {"id": "tx_01", "status": "pending"}}), calls)
    deposit = client.create_deposit(amount=100_000, phone="255712345678", reference="NOVA-ABCDEFGH",
                                    idempotency_key="intent-key-1", callback_url="https://app.example/hook")
    assert (deposit.id, deposit.status, deposit.replay) == ("tx_01", "pending", False)
    assert len(calls) == 1
    request = calls[0]
    body = request.content
    assert request.url == "https://abliner.test/api/v1/deposits"
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    assert request.headers["idempotency-key"] == "intent-key-1"
    assert request.headers["x-abliner-timestamp"] == "1790000000"
    expected = hmac.new(SECRET.encode(), b"1790000000." + body, hashlib.sha256).hexdigest()
    assert request.headers["x-abliner-signature"] == expected == sign(SECRET, "1790000000", body)
    assert json.loads(body) == {"amount": 100_000, "method": "mobile", "currency": "TZS", "phone": "255712345678",
                                "reference": "NOVA-ABCDEFGH", "callback_url": "https://app.example/hook"}


def test_one_attempt_only_and_uncertain_outcomes(configured):
    calls = []

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(AblinerError) as caught:
        _client(timeout, calls).create_deposit(amount=500, phone="255712345678", reference="NOVA-X", idempotency_key="k" * 8,
                                               callback_url="https://x")
    assert caught.value.code == "timeout" and caught.value.uncertain is True and len(calls) == 1
    calls.clear()
    with pytest.raises(AblinerError) as caught:
        _client(lambda r: httpx.Response(409, json={"status": "error", "code": "ussd_session_busy", "retryable": False}),
                calls).create_deposit(amount=500, phone="255712345678", reference="NOVA-X", idempotency_key="k" * 8,
                                      callback_url="https://x")
    assert (caught.value.code, caught.value.http_status, caught.value.uncertain) == ("ussd_session_busy", 409, False)
    assert len(calls) == 1


def test_not_configured_means_no_call(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "abliner_api_key", SecretStr(""))
    calls = []
    with pytest.raises(AblinerError) as caught:
        _client(lambda r: httpx.Response(200, json={}), calls).check_connection()
    assert caught.value.code == "not_configured" and calls == []


def test_secrets_never_reach_repr_logs_or_errors(configured, caplog):
    caplog.set_level(logging.DEBUG)
    settings = get_settings()
    assert API_KEY not in repr(settings) and SECRET not in repr(settings)
    client = _client(lambda r: httpx.Response(401, json={"status": "error", "code": "invalid_request_signature"}), [])
    assert API_KEY not in repr(client)
    with pytest.raises(AblinerError) as caught:
        client.create_deposit(amount=500, phone="255712345678", reference="NOVA-X", idempotency_key="k" * 8,
                              callback_url="https://x")
    text = str(caught.value) + repr(caught.value) + caplog.text
    for secret in (API_KEY, SECRET, "255712345678"):
        assert secret not in text


@pytest.mark.parametrize("code, status, ours, http", [
    ("ussd_session_busy", 409, "phone_busy", 409),
    ("request_in_progress", 409, "payment_in_progress", 409),
    ("idempotency_conflict", 409, "payment_in_progress", 409),
    ("amount_out_of_range", 422, "amount_out_of_range", 422),
    ("invalid_phone", 422, "invalid_phone", 422),
    ("unsupported_request", 422, "network_unsupported", 422),
    ("daily_limit_exceeded", 422, "gateway_daily_limit", 422),
    ("rate_limited", 429, "gateway_busy", 429),
    ("provider_error", 502, "gateway_unavailable", 502),
    ("gateway_not_configured", 503, "gateway_unavailable", 502),
    ("timeout", None, "gateway_unavailable", 502),
    ("unauthorized", 401, "gateway_misconfigured", 503),
    ("invalid_request_signature", 401, "gateway_misconfigured", 503),
    ("idempotency_key_required", 400, "gateway_misconfigured", 503),
    ("insufficient_funds", 402, "gateway_misconfigured", 503),
    ("http_403", 403, "gateway_misconfigured", 503),
    ("something_new", 500, "gateway_unavailable", 502),
])
def test_error_mapping(code, status, ours, http):
    mapped = map_error(code, status)
    assert (mapped.code, mapped.status) == (ours, http) and mapped.message


@pytest.mark.parametrize("raw, expected", [
    ("0712 345 678", "255712345678"), ("+255712345678", "255712345678"), ("255 712-345-678", "255712345678"),
    ("712345678", "255712345678"), ("0612345678", "255612345678"),
])
def test_phone_normalisation(raw, expected):
    assert phones.normalise(raw) == expected


@pytest.mark.parametrize("raw", ["", "0812345678", "256712345678", "25571234567", "2557123456789", "+254712345678", "abc"])
def test_phone_rejected(raw):
    with pytest.raises(phones.PhoneInvalid):
        phones.normalise(raw)


def test_phone_is_masked_and_never_hashed():
    assert phones.masked("255712345678") == "2557•••••678"
    assert not hasattr(phones, "digest")  # security review M4: no hash of the number is computed or kept
