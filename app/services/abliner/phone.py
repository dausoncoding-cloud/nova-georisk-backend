"""Tanzanian Mobile Money numbers: normalise to 255 + 9 digits (2556… / 2557…), mask and hash."""
from __future__ import annotations

import hashlib
import re

MESSAGE = "Enter a Tanzanian mobile number (for example 0712 345 678)."
_SEPARATORS = re.compile(r"[\s\-().]")
_VALID = re.compile(r"^255[67]\d{8}$")


class PhoneInvalid(ValueError):
    pass


def normalise(raw: str | None) -> str:
    value = _SEPARATORS.sub("", raw or "")
    if value.startswith("+"):
        value = value[1:]
    if value.startswith("0") and len(value) == 10:
        value = "255" + value[1:]
    elif len(value) == 9 and value[:1] in {"6", "7"}:
        value = "255" + value
    if not _VALID.fullmatch(value):
        raise PhoneInvalid(MESSAGE)
    return value


def masked(phone: str) -> str:
    return f"{phone[:4]}{'•' * 5}{phone[-3:]}"


def digest(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()
