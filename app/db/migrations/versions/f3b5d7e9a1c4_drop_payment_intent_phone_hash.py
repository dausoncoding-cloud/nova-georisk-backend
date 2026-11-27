"""Security review M4: drop payment_intents.phone_sha256 (masked phone only).

An unsalted SHA-256 of a Tanzanian mobile number (255 + 9 digits) is reversible in seconds, and nothing read it.
The intent keeps `phone_masked` only.

Downgrade re-adds the column as nullable: the hashes were never kept, so they cannot be restored, and the
pre-review code fills it for new intents. Nothing is lost by the downgrade itself.

Revision ID: f3b5d7e9a1c4
Revises: d7f9b1c3e5a8
"""
import sqlalchemy as sa
from alembic import op

revision = "f3b5d7e9a1c4"
down_revision = "d7f9b1c3e5a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("payment_intents", "phone_sha256")


def downgrade() -> None:
    op.add_column("payment_intents", sa.Column("phone_sha256", sa.String(64), nullable=True))
