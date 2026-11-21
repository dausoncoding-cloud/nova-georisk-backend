"""Operator command, run inside the API container (cron, for example every 15 minutes):

    python -m app.services.usage.cli flush

Moves the Redis usage buffer (API requests, downloads) into organization_usage_daily.
"""
from __future__ import annotations

import json

from app.db.session import SessionLocal
from app.services.usage.counters import flush


def main() -> int:
    db = SessionLocal()
    try:
        print(json.dumps({"organization_days": flush(db)}))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
