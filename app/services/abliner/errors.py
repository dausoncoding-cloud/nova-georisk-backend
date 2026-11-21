"""Abliner error codes -> our stable codes, HTTP status and the customer's message (plan §8)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mapped:
    code: str
    status: int
    message: str
    operator_alert: bool = False


UNAVAILABLE = "Mobile Money payments are unavailable right now. Contact NOVAREX."
NO_RESPONSE = ("The payment service didn't respond. If your phone shows a prompt, approve it; "
               "otherwise try again later.")

_BY_CODE = {
    "ussd_session_busy": Mapped("phone_busy", 409,
                                "There is already a payment prompt on this phone. Finish or cancel it, then try again."),
    "idempotency_conflict": Mapped("payment_in_progress", 409, "This payment is already being processed."),
    "request_in_progress": Mapped("payment_in_progress", 409, "This payment is already being processed."),
    "amount_out_of_range": Mapped("amount_out_of_range", 422,
                                  "This amount can't be paid by Mobile Money. Contact NOVAREX."),
    "invalid_phone": Mapped("invalid_phone", 422,
                            "This phone number can't receive Mobile Money prompts. Check the number."),
    "unsupported_request": Mapped("network_unsupported", 422,
                                  "This mobile network isn't supported yet. Contact NOVAREX."),
    "daily_limit_exceeded": Mapped("gateway_daily_limit", 422,
                                   "Mobile Money payments are paused for today. Try again tomorrow or contact NOVAREX."),
    "rate_limited": Mapped("gateway_busy", 429, "The payment service is busy. Try again in a minute."),
    "provider_error": Mapped("gateway_unavailable", 502, NO_RESPONSE),
    "gateway_not_configured": Mapped("gateway_unavailable", 502, NO_RESPONSE),
    "internal_error": Mapped("gateway_unavailable", 502, NO_RESPONSE),
    "timeout": Mapped("gateway_unavailable", 502, NO_RESPONSE),
    "network": Mapped("gateway_unavailable", 502, NO_RESPONSE),
    "bad_response": Mapped("gateway_unavailable", 502, NO_RESPONSE),
}
_MISCONFIGURED = {"unauthorized", "invalid_request_signature", "idempotency_key_required", "webhook_secret_required",
                  "insufficient_funds", "forbidden", "not_configured", "invalid_json", "validation_failed"}


def map_error(code: str | None, http_status: int | None = None) -> Mapped:
    if code in _BY_CODE:
        return _BY_CODE[code]
    if code in _MISCONFIGURED or http_status in {400, 401, 402, 403}:
        return Mapped("gateway_misconfigured", 503, UNAVAILABLE, operator_alert=True)
    if http_status == 429:
        return _BY_CODE["rate_limited"]
    return Mapped("gateway_unavailable", 502, NO_RESPONSE)
