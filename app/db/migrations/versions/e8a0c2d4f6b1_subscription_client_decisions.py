"""Client decisions on the subscription questions (2026-11-21): payment receipts (Q6) and storage requests (Q5).

- receipt_counters, payment_receipts: one receipt per existing and future payment except reversals, numbered
  in payment order without gaps; test payments in their own series.
- subscription_requests: kind "storage" with storage_gb.
Prices, limits and settings are not changed here: plans.v2.json is applied by `billing.cli apply-catalogue`.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "e8a0c2d4f6b1"
down_revision = "f3b5d7e9a1c4"  # security review M4 migration sits between the two
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "receipt_counters",
        sa.Column("series", sa.String(16), primary_key=True),
        sa.Column("last_number", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("series IN ('receipt','test')", name="ck_receipt_counter_series"),
    )
    op.create_table(
        "payment_receipts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("payment_id", UUID(as_uuid=True), sa.ForeignKey("payments.id"), nullable=False, unique=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("series", sa.String(16), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seller", JSONB(), nullable=True),
        sa.UniqueConstraint("series", "number", name="uq_receipt_number"),
        sa.CheckConstraint("series IN ('receipt','test')", name="ck_receipt_series"),
        sa.CheckConstraint("number > 0", name="ck_receipt_number_positive"),
    )
    op.create_index("ix_payment_receipts_organization_id", "payment_receipts", ["organization_id"])
    # Existing payments, in the order they were recorded.
    op.execute("""
        INSERT INTO payment_receipts (id, payment_id, organization_id, series, number, issued_at)
        SELECT gen_random_uuid(), p.id, p.organization_id,
               CASE WHEN p.purpose = 'test' THEN 'test' ELSE 'receipt' END,
               row_number() OVER (PARTITION BY (p.purpose = 'test') ORDER BY p.created_at, p.id),
               p.created_at
        FROM payments p WHERE p.purpose <> 'reversal'
    """)
    op.execute("""
        INSERT INTO receipt_counters (series, last_number)
        SELECT s.series, coalesce((SELECT max(number) FROM payment_receipts r WHERE r.series = s.series), 0)
        FROM (VALUES ('receipt'), ('test')) AS s(series)
    """)
    op.add_column("subscription_requests", sa.Column("storage_gb", sa.Integer(), nullable=True))
    op.drop_constraint("ck_subscription_request_kind", "subscription_requests", type_="check")
    op.create_check_constraint("ck_subscription_request_kind", "subscription_requests",
                               "kind IN ('top_up','upgrade','storage')")
    op.create_check_constraint("ck_subscription_request_storage", "subscription_requests",
                               "kind <> 'storage' OR (storage_gb IS NOT NULL AND storage_gb BETWEEN 1 AND 10000)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM subscription_requests WHERE kind = 'storage')")).scalar():
        raise RuntimeError("subscription_requests holds storage requests; close and remove them first.")
    # Receipts already handed to customers keep their numbers only while this table exists.
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM payment_receipts WHERE seller IS NOT NULL)")).scalar():
        raise RuntimeError("Receipts have been drawn for customers; their numbers cannot be removed.")
    op.drop_constraint("ck_subscription_request_storage", "subscription_requests", type_="check")
    op.drop_constraint("ck_subscription_request_kind", "subscription_requests", type_="check")
    op.create_check_constraint("ck_subscription_request_kind", "subscription_requests", "kind IN ('top_up','upgrade')")
    op.drop_column("subscription_requests", "storage_gb")
    op.drop_index("ix_payment_receipts_organization_id", table_name="payment_receipts")
    op.drop_table("payment_receipts")
    op.drop_table("receipt_counters")
