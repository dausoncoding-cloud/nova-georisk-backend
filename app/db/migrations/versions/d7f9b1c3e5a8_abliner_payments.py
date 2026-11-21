"""Abliner Mobile Money: payment_intents, abliner_webhook_events, integration_status.

Revision ID: d7f9b1c3e5a8
Revises: c5e7a9b1d3f6
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "d7f9b1c3e5a8"
down_revision = "c5e7a9b1d3f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_intents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", UUID(as_uuid=True), sa.ForeignKey("organization_subscriptions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=True),
        sa.Column("covers_from", sa.Date(), nullable=True),
        sa.Column("covers_until", sa.Date(), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("phone_masked", sa.String(32), nullable=False),
        sa.Column("phone_sha256", sa.String(64), nullable=False),
        sa.Column("reference", sa.String(40), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("request_key", sa.String(200), nullable=False, unique=True),
        sa.Column("abliner_tx_id", sa.String(80), nullable=True),
        sa.Column("abliner_event_tx_id", sa.String(80), nullable=True),
        sa.Column("provider_reference", sa.String(120), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failure_code", sa.String(60), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("payment_id", UUID(as_uuid=True), sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("purpose IN ('top_up','renewal')", name="ck_payment_intent_purpose"),
        sa.CheckConstraint("status IN ('created','pending','pending_unknown','completed','failed','expired','review')",
                           name="ck_payment_intent_status"),
        sa.CheckConstraint("amount > 0", name="ck_payment_intent_amount"),
        sa.CheckConstraint("purpose <> 'top_up' OR (credits IS NOT NULL AND credits > 0)", name="ck_payment_intent_credits"),
        sa.CheckConstraint("purpose <> 'renewal' OR (covers_from IS NOT NULL AND covers_until IS NOT NULL)",
                           name="ck_payment_intent_period"),
    )
    op.create_index("ix_payment_intents_organization_id", "payment_intents", ["organization_id"])
    op.create_index("ix_payment_intents_abliner_tx_id", "payment_intents", ["abliner_tx_id"])
    op.create_index("ix_payment_intents_created_at", "payment_intents", ["created_at"])
    op.create_index("uq_payment_intent_open", "payment_intents", ["subscription_id", "purpose"], unique=True,
                    postgresql_where=sa.text("status IN ('created','pending','pending_unknown')"))
    op.create_table(
        "abliner_webhook_events",
        sa.Column("webhook_id", sa.String(120), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event", sa.String(60), nullable=True),
        sa.Column("abliner_tx_id", sa.String(80), nullable=True),
        sa.Column("customer_reference", sa.String(80), nullable=True),
        sa.Column("remote_status", sa.String(30), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("intent_id", UUID(as_uuid=True), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=True),
    )
    op.create_index("ix_abliner_webhook_events_received_at", "abliner_webhook_events", ["received_at"])
    op.create_table(
        "integration_status",
        sa.Column("name", sa.String(30), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(60), nullable=True),
        sa.Column("last_webhook_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_webhook_event", sa.String(60), nullable=True),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM payment_intents)")).scalar():
        raise RuntimeError("payment_intents is not empty; export it before downgrading.")
    op.drop_table("integration_status")
    op.drop_table("abliner_webhook_events")
    op.drop_table("payment_intents")
