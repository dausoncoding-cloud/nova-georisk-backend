"""Operator commands, run inside the API container (docs/ABLINER_PAYMENTS_PLAN.md §5):

    python -m app.services.abliner.cli reconcile [--apply]   # cron every 10 minutes with --apply (flock, log)

Prints JSON counts only: no phone numbers, no payloads, no secrets.
"""
from __future__ import annotations

import argparse
import json

from app.db.session import SessionLocal
from app.services.abliner import reconcile
from app.services.abliner.client import get_client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.services.abliner.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("reconcile")
    run.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        report = reconcile.run(db, get_client(), apply=args.apply)
        print(json.dumps({"mode": report.mode, "checked": report.checked, "outcomes": report.counts}))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
