"""Persist sourced live events, reviewed-rule alerts and append-only feedback.

Revision ID: e8b5c2a71f40
Revises: d4e7b19c6a20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
revision = 'e8b5c2a71f40'
down_revision = 'd4e7b19c6a20'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('firris_live_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('sequence', sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column('project_id', UUID(as_uuid=True), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('policy_dataset_id', UUID(as_uuid=True), sa.ForeignKey('datasets.id'), nullable=False),
        sa.Column('event_key', sa.String(128), nullable=False),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('payload_sha256', sa.String(64), nullable=False),
        sa.Column('source_snapshot', JSONB(), nullable=False),
        sa.Column('alerts', JSONB(), nullable=False),
        sa.Column('actor_id', UUID(as_uuid=True), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('project_id','policy_dataset_id','event_key',name='uq_live_event_identity'))
    op.create_index('ix_firris_live_events_sequence','firris_live_events',['sequence'],unique=True)
    op.create_index('ix_firris_live_events_project_id','firris_live_events',['project_id'])
    op.create_table('firris_live_feedback',
        sa.Column('id',UUID(as_uuid=True),primary_key=True),
        sa.Column('event_id',UUID(as_uuid=True),sa.ForeignKey('firris_live_events.id'),nullable=False),
        sa.Column('actor_id',UUID(as_uuid=True),nullable=True),
        sa.Column('verdict',sa.String(32),nullable=False),
        sa.Column('notes',sa.String(2000),nullable=False),
        sa.Column('evidence_references',JSONB(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_firris_live_feedback_event_id','firris_live_feedback',['event_id'])


def downgrade():
    op.drop_table('firris_live_feedback')
    op.drop_table('firris_live_events')
