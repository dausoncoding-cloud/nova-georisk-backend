"""Operator commands, run inside the API container (no scripts are copied into any image):

    python -m app.services.billing.cli seed            # idempotent plan catalogue seed
    python -m app.services.billing.cli grant-monthly   # bring every subscription to this billing month

Both are safe to repeat; ledger idempotency keys make the monthly grant run once per month.
"""
from __future__ import annotations

import argparse
import json

from app.db.session import SessionLocal
from app.models.platform import OrganizationSubscription
from app.services.billing import catalogue, ledger


def grant_monthly(db) -> dict:
    granted = 0
    ids = [row.id for row in db.query(OrganizationSubscription.id).filter(OrganizationSubscription.family.isnot(None))]
    for subscription_id in ids:
        subscription = ledger.lock_subscription(db, subscription_id)
        before = ledger.entry_by_key(db, ledger.grant_key(subscription.id, ledger.period_of()))
        ledger.ensure_period(db, subscription)
        after = ledger.entry_by_key(db, ledger.grant_key(subscription.id, ledger.period_of()))
        granted += int(before is None and after is not None)
        db.commit()
    return {"subscriptions": len(ids), "granted": granted, "period": ledger.period_of()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.services.billing.cli")
    parser.add_argument("command", choices=["seed", "grant-monthly"])
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        if args.command == "seed":
            report = catalogue.seed_catalogue(db)
            db.commit()
            print(json.dumps({"plans": report.plans, "engine_links": report.engine_links, "prices": report.prices}))
        else:
            print(json.dumps(grant_monthly(db)))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
