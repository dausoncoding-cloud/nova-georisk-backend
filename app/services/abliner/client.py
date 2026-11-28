"""Abliner HTTP client (plan §2).

- Authorization: Bearer <ABLINER_API_KEY>, read from the environment at call time (SecretStr).
- POST /api/v1/deposits is always signed (x-abliner-timestamp, x-abliner-signature = hex HMAC-SHA256 of
  "<timestamp>.<exact body bytes>" keyed with ABLINER_WEBHOOK_SECRET, as in Abliner's code sample). The
  body is serialised once; the same bytes are signed and sent.
- One HTTP attempt per call, never an automatic retry with a new Idempotency-Key. Timeouts: connect 5 s,
  read 15 s.
- No secret, phone number, body or header ever reaches a log line, an exception message or repr().
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from app.core.config import get_settings

TIMEOUT = httpx.Timeout(20.0, connect=5.0, read=15.0)


class AblinerError(Exception):
    """A failed call. `code` is Abliner's error code (or timeout / network / bad_response / not_configured);
    `created` is True when Abliner says a transaction exists (transaction_id in the error)."""

    def __init__(self, code: str, http_status: int | None = None, *, retryable: bool = False,
                 transaction_id: str | None = None, uncertain: bool = False):
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.retryable = retryable
        self.transaction_id = transaction_id
        # True when we cannot tell whether a push was sent (timeout, network, unreadable answer).
        self.uncertain = uncertain


@dataclass(frozen=True)
class Deposit:
    id: str | None
    status: str
    replay: bool


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256).hexdigest()


# Tests replace this with httpx.MockTransport; production uses the default transport.
transport_factory: Callable[[], httpx.BaseTransport | None] = lambda: None


class AblinerClient:
    def __init__(self, transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.time):
        self._transport = transport
        self._clock = clock

    def __repr__(self) -> str:  # never the key
        return "AblinerClient()"

    @staticmethod
    def configured() -> dict[str, bool]:
        settings = get_settings()
        return {"api_key": bool(settings.abliner_api_key.get_secret_value()),
                "webhook_secret": bool(settings.abliner_webhook_secret.get_secret_value())}

    def _request(self, method: str, path: str, *, body: bytes | None = None, headers: dict | None = None,
                 params: dict | None = None) -> dict:
        settings = get_settings()
        key = settings.abliner_api_key.get_secret_value()
        if not key:
            raise AblinerError("not_configured")
        all_headers = {"Authorization": f"Bearer {key}", "Accept": "application/json", **(headers or {})}
        url = f"{settings.abliner_api_base_url.rstrip('/')}/api/v1{path}"
        try:
            with httpx.Client(timeout=TIMEOUT, transport=self._transport or transport_factory()) as http:
                response = http.request(method, url, content=body, headers=all_headers, params=params)
        except httpx.TimeoutException:
            raise AblinerError("timeout", uncertain=True) from None
        except httpx.HTTPError:
            raise AblinerError("network", uncertain=True) from None
        try:
            payload: Any = response.json()
        except ValueError:
            raise AblinerError("bad_response", response.status_code, uncertain=response.status_code < 400) from None
        if response.status_code >= 400 or not isinstance(payload, dict) or payload.get("status") == "error":
            payload = payload if isinstance(payload, dict) else {}
            code = str(payload.get("code") or ("rate_limited" if response.status_code == 429 else f"http_{response.status_code}"))
            raise AblinerError(code[:60], response.status_code, retryable=bool(payload.get("retryable")),
                               transaction_id=str(payload["transaction_id"])[:80] if payload.get("transaction_id") else None)
        return payload

    def create_deposit(self, *, amount: int, phone: str, reference: str, idempotency_key: str,
                       callback_url: str) -> Deposit:
        secret = get_settings().abliner_webhook_secret.get_secret_value()
        if not secret:
            raise AblinerError("not_configured")
        body = json.dumps({"amount": amount, "method": "mobile", "currency": "TZS", "phone": phone,
                           "reference": reference, "callback_url": callback_url},
                          separators=(",", ":")).encode("utf-8")
        timestamp = str(int(self._clock()))
        payload = self._request("POST", "/deposits", body=body, headers={
            "Content-Type": "application/json", "Idempotency-Key": idempotency_key,
            "x-abliner-timestamp": timestamp, "x-abliner-signature": sign(secret, timestamp, body)})
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        return Deposit(id=str(data["id"])[:80] if data.get("id") else None, status=str(data.get("status") or "pending"),
                       replay=bool(data.get("idempotent_replay") or payload.get("idempotent_replay")))

    def transactions(self, *, customer_reference: str | None = None, idempotency_key: str | None = None) -> list[dict]:
        params = {key: value for key, value in (("customer_reference", customer_reference),
                                                 ("idempotency_key", idempotency_key)) if value}
        payload = self._request("GET", "/transactions", params={**params, "limit": 10})
        data = payload.get("data")
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def check_connection(self) -> None:
        """GET /balance; raises AblinerError on failure. The balance itself is discarded, never returned."""
        self._request("GET", "/balance")


def get_client() -> AblinerClient:
    return AblinerClient()
