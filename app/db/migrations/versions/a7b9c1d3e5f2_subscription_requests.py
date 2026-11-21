"""Subscriptions M5: subscription_requests ("Request top-up" / "Request upgrade").

Revision ID: a7b9c1d3e5f2
Revises: f2c4e6a8b0d5
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "a7b9c1d3e5f2"
down_revision = "f2c4e6a8b0d5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "subscription_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("subscription_id", UUID(as_uuid=True),
                  sa.ForeignKey("organization_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("plan_key", sa.String(64), nullable=True),
        sa.Column("credits", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("close_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("kind IN ('top_up','upgrade')", name="ck_subscription_request_kind"),
        sa.CheckConstraint("status IN ('open','done','declined')", name="ck_subscription_request_status"),
        sa.CheckConstraint("kind <> 'upgrade' OR plan_key IS NOT NULL", name="ck_subscription_request_plan"),
        sa.CheckConstraint("kind <> 'top_up' OR (credits IS NOT NULL AND credits > 0)",
                           name="ck_subscription_request_credits"),
        sa.CheckConstraint("(status = 'open') = (closed_at IS NULL)", name="ck_subscription_request_closed"),
    )
    op.create_index("ix_subscription_requests_organization_id", "subscription_requests", ["organization_id"])
    op.create_index("ix_subscription_requests_created_at", "subscription_requests", ["created_at"])
    op.create_index("uq_subscription_request_open", "subscription_requests", ["subscription_id", "kind"], unique=True,
                    postgresql_where=sa.text("status = 'open'"))


def downgrade():
    op.drop_table("subscription_requests")
