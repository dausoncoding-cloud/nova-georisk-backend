"""Independent review 3-4: console_request_keys, one Idempotency-Key namespace for all NOVA ARI console writes.

Revision ID: c5e7a9b1d3f6
Revises: b3d5f7a9c1e4
"""
import sqlalchemy as sa
from alembic import op

revision = "c5e7a9b1d3f6"
down_revision = "b3d5f7a9c1e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "console_request_keys",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("console_request_keys")
