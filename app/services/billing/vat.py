"""VAT on what NOVA charges, from the seller settings (Q6, decided 2026-11-21; default "none").

- none:      the price is charged; the receipt shows "VAT: not charged".
- inclusive: the price is charged and includes VAT; the receipt splits it out.
- exclusive: VAT is added to the price; the customer pays price + VAT; the receipt splits it out.
Whole TZS, VAT rounded half up.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings


@dataclass(frozen=True)
class Split:
    net: int
    vat: int
    gross: int
    mode: str
    rate: int


def charge(price: int) -> int:
    """What the customer pays for a list price."""
    settings = get_settings()
    if settings.seller_vat_mode == "exclusive":
        return price + (price * settings.seller_vat_rate_percent * 2 + 100) // 200
    return price


def split(amount_paid: int) -> Split:
    """The VAT inside an amount paid (receipts)."""
    settings = get_settings()
    mode, rate = settings.seller_vat_mode, settings.seller_vat_rate_percent
    if mode == "none" or rate == 0:
        return Split(amount_paid, 0, amount_paid, mode, rate)
    vat = (amount_paid * rate * 2 + (100 + rate)) // (2 * (100 + rate))
    return Split(amount_paid - vat, vat, amount_paid, mode, rate)
