"""Durable sourced live events and append-only human feedback; no automatic relabelling."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, UUIDPrimaryKeyMixin


class LiveEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = 'firris_live_events'
    __table_args__ = (UniqueConstraint('project_id', 'policy_dataset_id', 'event_key', name='uq_live_event_identity'),)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('projects.id'), index=True)
    policy_dataset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('datasets.id'))
    event_key: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    source_snapshot: Mapped[dict] = mapped_column(JSONB)
    alerts: Mapped[list] = mapped_column(JSONB)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class LiveFeedback(UUIDPrimaryKeyMixin, Base):
    __tablename__ = 'firris_live_feedback'
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('firris_live_events.id'), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    verdict: Mapped[str] = mapped_column(String(32))
    notes: Mapped[str] = mapped_column(String(2000))
    evidence_references: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
