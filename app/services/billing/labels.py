"""Customer-facing ledger labels (independent review 7, owner decision): NOVA ARI's reasons are internal.

Customers see one fixed label per entry type, never the free-text reason an admin typed. Reasons stay in the
NOVA ARI console and the audit log. Refund labels come from the refund's recorded cause, not from its text.
"""
from __future__ import annotations

from app.models.billing import CreditLedgerEntry

REFUND_LABELS = {
    "data_failure": "Refund · analysis stopped (not enough valid satellite data)",
    "queue_failure": "Refund · analysis could not start",
}


def customer_label(entry: CreditLedgerEntry) -> str:
    metadata = entry.metadata_json or {}
    key = entry.idempotency_key or ""
    if entry.kind == "charge":
        return "Analysis"
    if entry.kind == "refund":
        return REFUND_LABELS.get(metadata.get("cause"), "Refund")
    if entry.kind == "monthly_grant":
        return "Monthly allowance"
    if entry.kind == "top_up":
        return "Credits added by NOVAREX" if metadata.get("granted") else "Top-up"
    if entry.kind == "expiry":
        return "Unused monthly credits expired"
    if key.startswith("planchange:"):
        return "Plan change"
    if key.startswith("reverse:"):
        return "Top-up reversed"
    return "Credit adjustment by NOVAREX"
