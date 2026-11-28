"""Operator command, run inside the API container (docs/ABLINER_PAYMENTS_PLAN.md §7):

    python -m app.services.integrations.cli check            # configured yes/no + Test connection per integration
    python -m app.services.integrations.cli check --no-test  # configuration only

Prints JSON with names of missing settings and result codes. Never a value, a key, a balance or a response body.

Rotation (owner, over SSH): edit the server's environment file, set the new ABLINER_API_KEY and/or
ABLINER_WEBHOOK_SECRET, restart api and worker (docker compose up -d api worker), run this check (Abliner must be
"connected"), update the webhook secret in the Abliner dashboard at the same time, then revoke the old key there.
"""
from __future__ import annotations

import argparse
import json

from app.db.session import SessionLocal
from app.services.integrations import checks, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.services.integrations.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("--no-test", action="store_true")
    check.add_argument("--name", choices=status.NAMES)
    args = parser.parse_args(argv)
    names = [args.name] if args.name else list(status.NAMES)
    report = []
    db = SessionLocal()
    try:
        for name in names:
            config = checks.configuration(name)
            item = {"name": name, "configured": config.configured, "missing": config.missing}
            if config.enabled is not None:
                item["enabled"] = config.enabled
            if not args.no_test:
                result = checks.test_connection(name)
                item["test"] = result
                if checks.ok(result):
                    status.success(db, name)
                elif result != "not_configured":
                    status.error(db, name, f"cli_{result}")
            report.append(item)
        db.commit()
    finally:
        db.close()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
