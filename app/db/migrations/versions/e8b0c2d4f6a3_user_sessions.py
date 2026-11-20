"""Subscriptions M3: user_sessions (device list, login history, session limit bookkeeping).

Revision ID: e8b0c2d4f6a3
Revises: c4e6a8b0d2f1
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "e8b0c2d4f6a3"
down_revision = "c4e6a8b0d2f1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("session_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(20), nullable=True),
        sa.Column("replaced_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("browser", sa.String(64), nullable=False),
        sa.Column("os", sa.String(64), nullable=False),
        sa.Column("device_type", sa.String(16), nullable=False),
        sa.Column("is_new_device", sa.Boolean(), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("city", sa.String(128), nullable=True),
        sa.Column("country", sa.String(128), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.CheckConstraint("end_reason IS NULL OR end_reason IN ('signed_out','replaced','ended_by_user','ended_by_admin')",
                           name="ck_user_session_end_reason"),
        sa.CheckConstraint("(ended_at IS NULL) = (end_reason IS NULL)", name="ck_user_session_ended"),
    )
    op.create_index("ix_user_sessions_user_created", "user_sessions", ["user_id", "created_at"])
    op.create_index("ix_user_sessions_org_created", "user_sessions", ["organization_id", "created_at"])


def downgrade():
    op.drop_table("user_sessions")
