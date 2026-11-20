"""Operator command, run inside the API container:

    python -m app.services.sessions.cli purge [--apply]

Removes full IP addresses older than SESSION_IP_RETENTION_DAYS (30; sign-in also does this) and,
once Q9 sets SESSION_HISTORY_RETENTION_DAYS, deletes older login history. Dry run unless --apply.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.sessions import UserSession
from app.services.sessions.tracking import drop_expired_ips


def purge(db, *, apply: bool, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    settings = get_settings()
    ip_cutoff = now - timedelta(days=settings.session_ip_retention_days)
    report = {"mode": "apply" if apply else "dry-run",
              "ip_addresses": db.query(UserSession).filter(UserSession.ip_address.isnot(None),
                                                           UserSession.created_at < ip_cutoff).count(),
              "history_rows": 0}
    history_days = settings.session_history_retention_days
    old = None
    if history_days is not None:
        old = db.query(UserSession).filter(UserSession.created_at < now - timedelta(days=history_days),
                                           UserSession.ended_at.isnot(None))
        report["history_rows"] = old.count()
    if apply:
        drop_expired_ips(db, now=now)
        if old is not None:
            old.delete(synchronize_session=False)
        db.commit()
    else:
        db.rollback()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.services.sessions.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    purge_parser = commands.add_parser("purge")
    purge_parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        print(json.dumps(purge(db, apply=args.apply)))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
