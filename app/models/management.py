"""Organization access audit and immutable scientific upload versions."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, CheckConstraint, event, DDL
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, UUIDPrimaryKeyMixin


class AccessAudit(UUIDPrimaryKeyMixin, Base):
    __tablename__ = 'access_audit'
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), index=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'))
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    previous: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    current: Mapped[dict] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ManagedDataset(UUIDPrimaryKeyMixin, Base):
    __tablename__ = 'managed_datasets'
    __table_args__ = (UniqueConstraint('series_id', 'version', name='uq_managed_dataset_version'), CheckConstraint('version > 0', name='ck_dataset_positive_version'))
    series_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('organizations.id'), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('projects.id'), index=True)
    aoi_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('aois.id'), nullable=True)
    uploader_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'))
    source_dataset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('datasets.id'), nullable=True, unique=True)
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(80))
    format: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(40), default='Uploaded')
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(512))
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    validation: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


AUDIT_FUNCTION = """CREATE OR REPLACE FUNCTION nova_immutable_access_audit() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'Access audit events are immutable'; END; $$ LANGUAGE plpgsql"""
AUDIT_TRIGGER = """CREATE TRIGGER immutable_access_audit BEFORE UPDATE OR DELETE ON access_audit
FOR EACH ROW EXECUTE FUNCTION nova_immutable_access_audit()"""
event.listen(AccessAudit.__table__, 'after_create', DDL(AUDIT_FUNCTION).execute_if(dialect='postgresql'))
event.listen(AccessAudit.__table__, 'after_create', DDL(AUDIT_TRIGGER).execute_if(dialect='postgresql'))

AUDIT_TRUNCATE_TRIGGER = """CREATE TRIGGER immutable_access_audit_truncate BEFORE TRUNCATE ON access_audit
FOR EACH STATEMENT EXECUTE FUNCTION nova_immutable_access_audit()"""
event.listen(AccessAudit.__table__, 'after_create', DDL(AUDIT_TRUNCATE_TRIGGER).execute_if(dialect='postgresql'))
