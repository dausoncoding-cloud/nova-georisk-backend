"""Read-only probe for the TZS 500 live test (billing phase 1, §5.7). Run ONLY at the test, after r15, inside the
API container via stdin, never copied into it:

    docker exec -i firris-release-2f1b2dc-firris-2f1b2dc-api-1 python - NOVA-XXXXXXXX < abliner_probe_transactions.py

It makes up to three GET /api/v1/transactions calls through the app's own client (?customer_reference=<ref>,
?id=<abliner_tx_id from our intent>, and the list form ?limit=5) and prints, per item, only: the field NAMES, the
id's SHAPE (tx_/uuid/other and length; never the id), amount, amount_cents, currency, status, and whether
customer_reference equals our reference. It never prints the API key, headers, provider_reference, phone numbers or
any other value. It answers the two open points: tx_ vs UUID, and amount vs amount_cents.
"""
import json
import re
import sys

from app.db.session import SessionLocal
from app.models.abliner import PaymentIntent
from app.services.abliner.client import AblinerError, get_client

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def shape(value) -> str:
    text = str(value or "")
    if not text:
        return "missing"
    return ("uuid" if UUID.match(text) else "tx_" if text.startswith("tx_") else "other") + f"/len{len(text)}"


def summary(items, reference):
    return [{"fields": sorted(item), "id_shape": shape(item.get("id")), "amount": item.get("amount"),
             "amount_cents": item.get("amount_cents"), "currency": item.get("currency"), "status": item.get("status"),
             "type": item.get("type"), "ours": item.get("customer_reference") == reference} for item in items]


reference = sys.argv[1]
db = SessionLocal()
intent = db.query(PaymentIntent).filter(PaymentIntent.reference == reference).one_or_none()
out = {"intent_found": intent is not None,
       "intent": None if intent is None else {"status": intent.status, "amount": intent.amount,
                                               "deposit_reply_id_shape": shape(intent.abliner_tx_id),
                                               "webhook_id_shape": shape(intent.abliner_event_tx_id),
                                               "ids_equal": bool(intent.abliner_tx_id) and intent.abliner_tx_id == intent.abliner_event_tx_id}}
client = get_client()
for label, call in (("by_customer_reference", lambda: client._request("GET", "/transactions", params={"customer_reference": reference})),
                    ("by_id", lambda: client._request("GET", "/transactions", params={"id": intent.abliner_tx_id}) if intent and intent.abliner_tx_id else None),
                    ("list_limit_5", lambda: client._request("GET", "/transactions", params={"limit": 5}))):
    try:
        payload = call()
        if payload is None:
            out[label] = "skipped (no abliner_tx_id)"
            continue
        data = payload.get("data")
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        out[label] = {"top_level_fields": sorted(payload), "data_type": type(data).__name__, "items": summary(items, reference)}
    except AblinerError as exc:
        out[label] = {"error": exc.code, "http_status": exc.http_status}
db.close()
print(json.dumps(out, indent=2))
