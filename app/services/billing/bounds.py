"""Bounds for plan limits and per-contract overrides (security review L2). One table, used by the console API
schemas and re-checked in the services, so every caller gets the same rules.

Seats and sessions start at 1: 0 would lock everyone out, and the session-limit script reads 0 as "no limit".
"""
from __future__ import annotations

INTEGER_BOUNDS: dict[str, tuple[int, int]] = {
    "monthly_credits": (0, 100_000),
    "seat_limit": (1, 10_000),
    "storage_bytes": (0, 100 * 10**12),  # 100 TB
    "session_limit": (1, 100),
}
OVERRIDE_FIELDS = {f"{name}_override": name for name in INTEGER_BOUNDS}
BOOLEAN_OVERRIDES = ("refund_on_data_failure_override",)


def check(name: str, value) -> str | None:
    """None when `value` is acceptable for the limit or override `name`, else a message."""
    base = OVERRIDE_FIELDS.get(name, name)
    if name in BOOLEAN_OVERRIDES or base == "refund_on_data_failure":
        return None if value is None or isinstance(value, bool) else f"{name} must be true, false or empty."
    if base not in INTEGER_BOUNDS:
        return f"Unknown field: {name}"
    if value is None:
        return None
    low, high = INTEGER_BOUNDS[base]
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        return f"{name} must be a whole number from {low} to {high}, or empty."
    return None
