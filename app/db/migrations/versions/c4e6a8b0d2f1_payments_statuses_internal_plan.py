"""Subscriptions M2: manual payments, platform audit, status timestamp, Internal plan.

Payments and platform_audit rows are immutable (the same UPDATE/DELETE/TRUNCATE trigger as the ledger).
Seeds the Internal plan of each family from app/services/billing/plans.v1.json (insert-only, no price).

Revision ID: c4e6a8b0d2f1
Revises: a9c3e5f70b12
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "c4e6a8b0d2f1"
down_revision = "a9c3e5f70b12"
branch_labels = None
depends_on = None

CATALOGUE = Path(__file__).resolve().parents[3] / "services" / "billing" / "plans.v1.json"
IMMUTABLE_TABLES = ("payments", "platform_audit")


def _internal_plans():
    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    for family, plans in catalogue["plans"].items():
        for item in plans:
            if item.get("is_internal"):
                yield catalogue, family, item


def upgrade():
    op.add_column("billing_plans", sa.Column("is_internal", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("billing_plans",
                  sa.Column("unlimited_credits", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("organization_subscriptions",
                  sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "payments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("subscription_id", UUID(as_uuid=True), sa.ForeignKey("organization_subscriptions.id"), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("reference", sa.String(255), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("covers_from", sa.Date(), nullable=True),
        sa.Column("covers_until", sa.Date(), nullable=True),
        sa.Column("credits", sa.Integer(), nullable=True),
        sa.Column("expected_amount", sa.BigInteger(), nullable=True),
        sa.Column("reverses_payment_id", UUID(as_uuid=True), sa.ForeignKey("payments.id"), nullable=True, unique=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("method IN ('bank_transfer','mobile_money','cash','other')", name="ck_payment_method"),
        sa.CheckConstraint("purpose IN ('plan_period','top_up','reversal')", name="ck_payment_purpose"),
        sa.CheckConstraint("(purpose = 'reversal') = (amount < 0)", name="ck_payment_sign"),
        sa.CheckConstraint("amount <> 0", name="ck_payment_amount_nonzero"),
        sa.CheckConstraint("purpose <> 'top_up' OR (credits IS NOT NULL AND credits > 0)", name="ck_payment_topup_credits"),
        sa.CheckConstraint("purpose <> 'plan_period' OR (covers_from IS NOT NULL AND covers_until IS NOT NULL "
                           "AND covers_until >= covers_from)", name="ck_payment_period"),
        sa.CheckConstraint("(purpose = 'reversal') = (reverses_payment_id IS NOT NULL)", name="ck_payment_reversal_link"),
        sa.CheckConstraint("purpose <> 'reversal' OR (note IS NOT NULL AND length(trim(note)) > 0)",
                           name="ck_payment_reversal_reason"),
    )
    op.create_index("ix_payments_organization_id", "payments", ["organization_id"])
    op.create_index("ix_payments_subscription_id", "payments", ["subscription_id"])

    op.create_table(
        "platform_audit",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_label", sa.String(255), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("target_type", sa.String(40), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("previous", JSONB, nullable=True),
        sa.Column("current", JSONB, nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_platform_audit_reason"),
        sa.CheckConstraint("actor_user_id IS NOT NULL OR actor_label IS NOT NULL", name="ck_platform_audit_actor"),
    )
    op.create_index("ix_platform_audit_action", "platform_audit", ["action"])
    op.create_index("ix_platform_audit_organization_id", "platform_audit", ["organization_id"])
    op.create_index("ix_platform_audit_created_at", "platform_audit", ["created_at"])

    # The function exists since a9c3e5f70b12; recreate it so this revision stands alone.
    op.execute("""CREATE OR REPLACE FUNCTION nova_immutable_billing_record() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION USING MESSAGE = TG_TABLE_NAME || ' rows are append-only'; END; $$ LANGUAGE plpgsql""")
    for table in IMMUTABLE_TABLES:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION nova_immutable_billing_record()")
        op.execute(f"CREATE TRIGGER immutable_{table}_truncate BEFORE TRUNCATE ON {table} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION nova_immutable_billing_record()")

    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    engines = {row[0] for row in bind.execute(sa.text("SELECT key FROM engines"))}
    for catalogue, family, item in _internal_plans():
        spec = catalogue["families"][family]
        bind.execute(sa.text(
            "INSERT INTO billing_plans (key, name, description, status, metadata, family, is_custom, seat_limit, "
            "monthly_credits, storage_bytes, session_limit, refund_on_data_failure, sort_order, is_internal, "
            "unlimited_credits, created_at, updated_at) "
            "VALUES (:key, :name, :description, 'active', CAST(:metadata AS jsonb), :family, false, NULL, NULL, NULL, "
            "NULL, false, :sort_order, true, :unlimited, :now, :now) ON CONFLICT (key) DO NOTHING"), {
                "key": item["key"], "name": item["name"], "description": f"{spec['name']} - {item['name']}",
                "metadata": json.dumps({"catalogue_version": catalogue["version"]}), "family": family,
                "sort_order": item["sort_order"], "unlimited": bool(item.get("unlimited_credits")), "now": now})
        for engine_key in spec["engines"]:
            if engine_key in engines:
                bind.execute(sa.text("INSERT INTO billing_plan_engines (plan_key, engine_key) VALUES (:plan, :engine) "
                                     "ON CONFLICT DO NOTHING"), {"plan": item["key"], "engine": engine_key})


def downgrade():
    bind = op.get_bind()
    for table in IMMUTABLE_TABLES:
        if bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar():
            raise RuntimeError(f"{table} is not empty; export it before downgrading.")
    keys = [item["key"] for _, _, item in _internal_plans()]
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM organization_subscriptions WHERE plan_key = ANY(:keys))"),
                    {"keys": keys}).scalar():
        raise RuntimeError("Subscriptions use the Internal plan; move them to another plan before downgrading.")
    for table in IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table}_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table} ON {table}")
    op.drop_table("platform_audit")
    op.drop_table("payments")
    bind.execute(sa.text("DELETE FROM billing_plans WHERE key = ANY(:keys)"), {"keys": keys})
    op.drop_column("organization_subscriptions", "status_changed_at")
    op.drop_column("billing_plans", "unlimited_credits")
    op.drop_column("billing_plans", "is_internal")
