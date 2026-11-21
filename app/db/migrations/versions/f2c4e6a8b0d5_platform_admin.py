"""Subscriptions M4: platform_admins (NOVA ARI role, granted by command only), security_alerts,
organization_usage_daily.

Revision ID: f2c4e6a8b0d5
Revises: e8b0c2d4f6a3
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "f2c4e6a8b0d5"
down_revision = "e8b0c2d4f6a3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_admins",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_by", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_platform_admin_reason"),
    )
    op.create_index("ix_platform_admins_user_id", "platform_admins", ["user_id"])
    op.create_index("uq_platform_admin_live", "platform_admins", ["user_id"], unique=True,
                    postgresql_where=sa.text("revoked_at IS NULL"))

    op.create_table(
        "security_alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", JSONB, nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("acknowledge_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("kind IN ('new_device')", name="ck_security_alert_kind"),
        sa.CheckConstraint("(acknowledged_at IS NULL) = (acknowledge_reason IS NULL)", name="ck_security_alert_ack"),
    )
    op.create_index("ix_security_alerts_organization_id", "security_alerts", ["organization_id"])
    op.create_index("ix_security_alerts_created_at", "security_alerts", ["created_at"])
    op.create_index("ix_security_alerts_open", "security_alerts", ["organization_id"],
                    postgresql_where=sa.text("acknowledged_at IS NULL"))

    op.create_table(
        "organization_usage_daily",
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("api_requests", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("downloads", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("download_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM platform_admins)")).scalar():
        raise RuntimeError("platform_admins is not empty; record the grants before downgrading.")
    op.drop_table("organization_usage_daily")
    op.drop_table("security_alerts")
    op.drop_table("platform_admins")
