"""Subscriptions M1: typed plan limits, versioned prices, append-only credit ledger, submission idempotency.

Seeds the plan catalogue from app/services/billing/plans.v1.json (insert-only). Ledger and price rows
are immutable (UPDATE/DELETE/TRUNCATE triggers), like access_audit.

Revision ID: a9c3e5f70b12
Revises: f1a2b3c4d5e6
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "a9c3e5f70b12"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None

CATALOGUE = Path(__file__).resolve().parents[3] / "services" / "billing" / "plans.v1.json"
IMMUTABLE_TABLES = ("credit_ledger_entries", "billing_plan_prices")


def upgrade():
    for column in (
        sa.Column("family", sa.String(32), nullable=True),
        sa.Column("is_custom", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("seat_limit", sa.Integer(), nullable=True),
        sa.Column("monthly_credits", sa.Integer(), nullable=True),
        sa.Column("storage_bytes", sa.BigInteger(), nullable=True),
        sa.Column("session_limit", sa.Integer(), nullable=True),
        sa.Column("refund_on_data_failure", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
    ):
        op.add_column("billing_plans", column)
    for column in (
        sa.Column("family", sa.String(32), nullable=True),
        sa.Column("monthly_credits_override", sa.Integer(), nullable=True),
        sa.Column("seat_limit_override", sa.Integer(), nullable=True),
        sa.Column("storage_bytes_override", sa.BigInteger(), nullable=True),
        sa.Column("session_limit_override", sa.Integer(), nullable=True),
        sa.Column("refund_on_data_failure_override", sa.Boolean(), nullable=True),
    ):
        op.add_column("organization_subscriptions", column)
    op.create_index("uq_subscription_org_family", "organization_subscriptions", ["organization_id", "family"],
                    unique=True, postgresql_where=sa.text("family IS NOT NULL"))

    op.create_table(
        "billing_plan_prices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_key", sa.String(64), sa.ForeignKey("billing_plans.key"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("monthly_price", sa.BigInteger(), nullable=True),
        sa.Column("top_up_credit_price", sa.BigInteger(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("plan_key", "version", name="uq_plan_price_version"),
        sa.CheckConstraint("version > 0", name="ck_plan_price_version_positive"),
        sa.CheckConstraint("monthly_price IS NULL OR monthly_price >= 0", name="ck_plan_price_non_negative"),
        sa.CheckConstraint("top_up_credit_price IS NULL OR top_up_credit_price > 0", name="ck_plan_topup_price_positive"),
    )
    op.create_index("ix_billing_plan_prices_plan_key", "billing_plan_prices", ["plan_key"])

    op.create_table(
        "credit_ledger_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("subscription_id", UUID(as_uuid=True), sa.ForeignKey("organization_subscriptions.id"), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("bucket", sa.String(10), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("bucket_balance_after", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("task_id", UUID(as_uuid=True), nullable=True),
        sa.Column("payment_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('monthly_grant','top_up','charge','refund','adjustment','expiry')", name="ck_ledger_kind"),
        sa.CheckConstraint("bucket IN ('monthly','top_up')", name="ck_ledger_bucket"),
        sa.CheckConstraint("amount <> 0", name="ck_ledger_amount_nonzero"),
        sa.CheckConstraint("balance_after >= 0", name="ck_ledger_balance_non_negative"),
        sa.CheckConstraint("bucket_balance_after >= 0", name="ck_ledger_bucket_balance_non_negative"),
        sa.CheckConstraint(
            "(kind IN ('monthly_grant','top_up','refund') AND amount > 0) OR "
            "(kind IN ('charge','expiry') AND amount < 0) OR kind = 'adjustment'",
            name="ck_ledger_amount_sign"),
        sa.CheckConstraint("kind <> 'adjustment' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
                           name="ck_ledger_adjustment_reason"),
        sa.CheckConstraint("kind NOT IN ('charge','refund') OR task_id IS NOT NULL", name="ck_ledger_task_link"),
        sa.CheckConstraint("period ~ '^[0-9]{4}-[0-9]{2}$'", name="ck_ledger_period_format"),
    )
    for column in ("subscription_id", "organization_id", "task_id"):
        op.create_index(f"ix_credit_ledger_entries_{column}", "credit_ledger_entries", [column])

    op.create_table(
        "submission_idempotency_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("endpoint", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("task_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", "key", name="uq_submission_idempotency"),
    )
    op.create_table(
        "credit_usage_notices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("subscription_id", UUID(as_uuid=True), sa.ForeignKey("organization_subscriptions.id"), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("subscription_id", "period", "level", name="uq_credit_usage_notice"),
        sa.CheckConstraint("level IN (75, 90, 100)", name="ck_credit_usage_notice_level"),
    )

    op.execute("""CREATE OR REPLACE FUNCTION nova_immutable_billing_record() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION USING MESSAGE = TG_TABLE_NAME || ' rows are append-only'; END; $$ LANGUAGE plpgsql""")
    for table in IMMUTABLE_TABLES:
        op.execute(f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION nova_immutable_billing_record()")
        op.execute(f"CREATE TRIGGER immutable_{table}_truncate BEFORE TRUNCATE ON {table} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION nova_immutable_billing_record()")

    _seed(op.get_bind())


def _seed(bind) -> None:
    import uuid

    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    engines = {row[0] for row in bind.execute(sa.text("SELECT key FROM engines"))}
    refund_default = bool(catalogue.get("refund_on_data_failure", False))
    for family, plans in catalogue["plans"].items():
        spec = catalogue["families"][family]
        for item in plans:
            bind.execute(sa.text(
                "INSERT INTO billing_plans (key, name, description, status, metadata, family, is_custom, seat_limit, "
                "monthly_credits, storage_bytes, session_limit, refund_on_data_failure, sort_order, created_at, updated_at) "
                "VALUES (:key, :name, :description, 'active', CAST(:metadata AS jsonb), :family, :is_custom, :seat_limit, "
                ":monthly_credits, :storage_bytes, :session_limit, :refund, :sort_order, :now, :now) "
                "ON CONFLICT (key) DO NOTHING"), {
                    "key": item["key"], "name": item["name"], "description": f"{spec['name']} - {item['name']}",
                    "metadata": json.dumps({"catalogue_version": catalogue["version"]}), "family": family,
                    "is_custom": item["is_custom"], "seat_limit": item["seat_limit"],
                    "monthly_credits": item["monthly_credits"], "storage_bytes": item["storage_bytes"],
                    "session_limit": item["session_limit"], "refund": item.get("refund_on_data_failure", refund_default),
                    "sort_order": item["sort_order"], "now": now})
            for engine_key in spec["engines"]:
                if engine_key in engines:
                    bind.execute(sa.text(
                        "INSERT INTO billing_plan_engines (plan_key, engine_key) VALUES (:plan, :engine) "
                        "ON CONFLICT DO NOTHING"), {"plan": item["key"], "engine": engine_key})
            bind.execute(sa.text(
                "INSERT INTO billing_plan_prices (id, plan_key, version, currency, monthly_price, top_up_credit_price, "
                "effective_from, source, reason, created_at) "
                "SELECT :id, :plan, 1, :currency, :price, :topup, :now, :source, :reason, :now "
                "WHERE NOT EXISTS (SELECT 1 FROM billing_plan_prices WHERE plan_key = :plan)"), {
                    "id": uuid.uuid4(), "plan": item["key"], "currency": catalogue["currency"],
                    "price": item["monthly_price"], "topup": spec["top_up_credit_price"], "now": now,
                    "source": f"plans.v{catalogue['version']}.json", "reason": catalogue["source"]})


def downgrade():
    # Financial records: refuse to drop a ledger that holds entries.
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM credit_ledger_entries)")).scalar():
        raise RuntimeError("credit_ledger_entries is not empty; export it before downgrading.")
    for table in IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table}_truncate ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS immutable_{table} ON {table}")
    op.execute("DROP FUNCTION IF EXISTS nova_immutable_billing_record()")
    # Remove the seeded catalogue rows too, so a later upgrade re-seeds them with their limits.
    keys = [item["key"] for plans in json.loads(CATALOGUE.read_text(encoding="utf-8"))["plans"].values() for item in plans]
    op.drop_table("credit_usage_notices")
    op.drop_table("submission_idempotency_keys")
    op.drop_table("credit_ledger_entries")
    op.drop_table("billing_plan_prices")
    bind.execute(sa.text("DELETE FROM billing_plans WHERE key = ANY(:keys)"), {"keys": keys})
    op.drop_index("uq_subscription_org_family", table_name="organization_subscriptions")
    for column in ("refund_on_data_failure_override", "session_limit_override", "storage_bytes_override",
                   "seat_limit_override", "monthly_credits_override", "family"):
        op.drop_column("organization_subscriptions", column)
    for column in ("sort_order", "refund_on_data_failure", "session_limit", "storage_bytes", "monthly_credits",
                   "seat_limit", "is_custom", "family"):
        op.drop_column("billing_plans", column)
