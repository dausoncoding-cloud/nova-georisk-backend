"""Persist approved administrative-boundary AOI lineage.

Revision ID: d4e7b19c6a20
Revises: c7f0a8d42e91
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "d4e7b19c6a20"
down_revision = "c7f0a8d42e91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("aois", sa.Column("source_lineage", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("aois", "source_lineage")
