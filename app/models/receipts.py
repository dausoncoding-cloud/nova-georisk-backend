"""Payment receipts (Q6, decided 2026-11-21): one per recorded payment, numbered without gaps.

"Payment receipt - not a TRA fiscal receipt". Issued in the same transaction as the payment, so numbers follow
payment order and a rolled-back payment leaves no gap (a locked counter row, not a sequence). Test payments get
their own series ("TEST-..."), so the real series stays gapless. Reversals get no receipt; the reversed
payment's receipt is drawn "REVERSED". The seller identity is frozen on the receipt when first drawn.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin

SERIES = ("receipt", "test")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReceiptCounter(Base):
    __tablename__ = "receipt_counters"
    __table_args__ = (CheckConstraint("series IN ('receipt','test')", name="ck_receipt_counter_series"),)
    series: Mapped[str] = mapped_column(String(16), primary_key=True)
    last_number: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class PaymentReceipt(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payment_receipts"
    __table_args__ = (
        UniqueConstraint("series", "number", name="uq_receipt_number"),
        CheckConstraint("series IN ('receipt','test')", name="ck_receipt_series"),
        CheckConstraint("number > 0", name="ck_receipt_number_positive"),
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payments.id"), nullable=False,
                                                  unique=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"),
                                                       nullable=False, index=True)
    series: Mapped[str] = mapped_column(String(16), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    # Seller name, TIN, address and VAT mode/rate as they were when the receipt was first drawn.
    seller: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
