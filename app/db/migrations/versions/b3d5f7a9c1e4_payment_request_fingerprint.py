"""Security review L5: payments.request_sha256 (the request an Idempotency-Key was first used with).

Adding a nullable column does not rewrite rows or fire the append-only row triggers. Earlier payments keep
NULL and are replayed as before.

Revision ID: b3d5f7a9c1e4
Revises: a7b9c1d3e5f2
"""
import sqlalchemy as sa
from alembic import op

revision = "b3d5f7a9c1e4"
down_revision = "a7b9c1d3e5f2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payments", sa.Column("request_sha256", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("payments", "request_sha256")
