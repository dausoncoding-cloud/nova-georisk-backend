"""OIDC invitation provisioning

Revision ID: 8d1c4b72e0af
Revises: 7f3d2a91c4be
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "8d1c4b72e0af"
down_revision = "7f3d2a91c4be"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE results SET aoi_id = tasks.aoi_id FROM tasks "
        "WHERE results.task_id = tasks.id AND results.aoi_id IS NULL"
    )
    op.alter_column("results", "project_id", nullable=False)
    # Reuse the membershiprole enum created by Phase 0 rather than attempting
    # to create a duplicate PostgreSQL type.
    membership_role = postgresql.ENUM(
        "OWNER", "ADMIN", "ANALYST", "VIEWER", name="membershiprole", create_type=False
    )
    op.create_table(
        "organization_invitations",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", membership_role, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_organization_invitations_token_hash"),
    )
    op.create_index(
        "ix_organization_invitations_email", "organization_invitations", ["email"]
    )
    op.create_index(
        "ix_organization_invitations_organization_id",
        "organization_invitations",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organization_invitations_organization_id",
        table_name="organization_invitations",
    )
    op.drop_index("ix_organization_invitations_email", table_name="organization_invitations")
    op.drop_table("organization_invitations")
    op.alter_column("results", "project_id", nullable=True)
