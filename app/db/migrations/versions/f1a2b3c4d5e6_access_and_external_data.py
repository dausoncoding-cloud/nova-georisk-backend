"""Add scoped membership state, append-only audit, and external dataset versions.

Revision ID: f1a2b3c4d5e6
Revises: e8b5c2a71f40
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
revision='f1a2b3c4d5e6'
down_revision='e8b5c2a71f40'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('organization_memberships',sa.Column('status',sa.String(20),nullable=False,server_default='active'))
    op.create_check_constraint('ck_membership_status','organization_memberships',"status IN ('active','disabled','removed')")
    op.create_table('access_audit',
        sa.Column('id',UUID(as_uuid=True),primary_key=True),
        sa.Column('organization_id',UUID(as_uuid=True),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('actor_user_id',UUID(as_uuid=True),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('target_user_id',UUID(as_uuid=True),sa.ForeignKey('users.id'),nullable=True),
        sa.Column('action',sa.String(80),nullable=False),sa.Column('previous',JSONB(),nullable=True),
        sa.Column('current',JSONB(),nullable=False),sa.Column('request_id',sa.String(128),nullable=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_access_audit_organization_id','access_audit',['organization_id'])
    op.execute("""CREATE OR REPLACE FUNCTION nova_immutable_access_audit() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'Access audit events are immutable'; END; $$ LANGUAGE plpgsql""")
    op.execute('CREATE TRIGGER immutable_access_audit BEFORE UPDATE OR DELETE ON access_audit FOR EACH ROW EXECUTE FUNCTION nova_immutable_access_audit()')
    op.execute('CREATE TRIGGER immutable_access_audit_truncate BEFORE TRUNCATE ON access_audit FOR EACH STATEMENT EXECUTE FUNCTION nova_immutable_access_audit()')
    op.create_table('managed_datasets',
        sa.Column('id',UUID(as_uuid=True),primary_key=True),sa.Column('series_id',UUID(as_uuid=True),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('organization_id',UUID(as_uuid=True),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('project_id',UUID(as_uuid=True),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('aoi_id',UUID(as_uuid=True),sa.ForeignKey('aois.id'),nullable=True),
        sa.Column('uploader_id',UUID(as_uuid=True),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('source_dataset_id',UUID(as_uuid=True),sa.ForeignKey('datasets.id'),nullable=True,unique=True),
        sa.Column('title',sa.String(255),nullable=False),sa.Column('category',sa.String(80),nullable=False),
        sa.Column('format',sa.String(20),nullable=False),sa.Column('status',sa.String(40),nullable=False),
        sa.Column('sha256',sa.String(64),nullable=False),sa.Column('size_bytes',sa.Integer(),nullable=False),
        sa.Column('storage_key',sa.String(512),nullable=False),sa.Column('metadata_json',JSONB(),nullable=False),
        sa.Column('validation',JSONB(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('series_id','version',name='uq_managed_dataset_version'),
        sa.CheckConstraint('version > 0',name='ck_dataset_positive_version'))
    for field in ['series_id','organization_id','project_id']:
        op.create_index('ix_managed_datasets_'+field,'managed_datasets',[field])


def downgrade():
    # Retain access/history: application rollback uses the previous image with this additive schema.
    raise RuntimeError('Destructive downgrade refused: archive/export managed data and audit under a separately reviewed recovery procedure.')
