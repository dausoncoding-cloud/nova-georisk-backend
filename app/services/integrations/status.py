"""integration_status rows: last success, last error code, last webhook. Codes and times only: never a value,
a payload or a message from the other side. Writes are best-effort and never fail the caller."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.abliner import IntegrationStatus

logger = logging.getLogger(__name__)
NAMES = ("abliner", "gee", "auth0")


def _row(db: Session, name: str) -> IntegrationStatus:
    row = db.get(IntegrationStatus, name)
    if row is None:
        row = IntegrationStatus(name=name)
        db.add(row)
    return row


def _write(db: Session, name: str, **fields) -> None:
    try:
        with db.begin_nested():
            row = _row(db, name)
            for key, value in fields.items():
                setattr(row, key, value)
            db.flush()
    except Exception:
        logger.warning("Integration status not recorded for %s", name)


def success(db: Session, name: str) -> None:
    _write(db, name, last_success_at=datetime.now(timezone.utc))


def error(db: Session, name: str, code: str) -> None:
    _write(db, name, last_error_at=datetime.now(timezone.utc), last_error_code=(code or "error")[:60])


def webhook(db: Session, name: str, event: str | None) -> None:
    _write(db, name, last_webhook_at=datetime.now(timezone.utc), last_webhook_event=(event or "unknown")[:60])
