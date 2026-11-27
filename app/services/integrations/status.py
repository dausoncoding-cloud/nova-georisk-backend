"""integration_status rows: last success, last error code, last webhook. Codes and times only: never a value,
a payload or a message from the other side. Writes are best-effort and never fail the caller."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.abliner import IntegrationStatus

logger = logging.getLogger(__name__)
NAMES = ("abliner", "gee", "auth0")

# Security review L3: rejections of unauthenticated requests (bad signature, stale timestamp, ...) are written at
# most once a minute, and never over an error from an authenticated source (settlement, reconciliation, a test)
# that is less than a day old, so anyone on the internet can neither load the table nor hide a real error.
UNVERIFIED_MIN_INTERVAL = timedelta(seconds=60)
UNVERIFIED_KEEPS_REAL_ERROR = timedelta(hours=24)
UNVERIFIED_PREFIX = "webhook_"


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


def unverified_error(db: Session, name: str, code: str, now: datetime | None = None) -> bool:
    """L3: an unauthenticated rejection. Returns True when it was recorded."""
    now = now or datetime.now(timezone.utc)
    code = f"{UNVERIFIED_PREFIX}{code or 'error'}"[:60]
    row = db.get(IntegrationStatus, name)
    if row is not None and row.last_error_at is not None:
        age = now - row.last_error_at
        if age < UNVERIFIED_MIN_INTERVAL:
            return False
        if not (row.last_error_code or "").startswith(UNVERIFIED_PREFIX) and age < UNVERIFIED_KEEPS_REAL_ERROR:
            return False
    _write(db, name, last_error_at=now, last_error_code=code)
    return True
