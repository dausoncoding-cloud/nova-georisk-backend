"""Operator commands, run inside the API container (no scripts are copied into any image):

    python -m app.services.billing.cli seed            # idempotent plan catalogue seed
    python -m app.services.billing.cli grant-monthly   # bring every subscription to this billing month
    python -m app.services.billing.cli backfill-subscriptions --plan frris_wrris=frris_wrris.professional \\
        --internal-org novarex --internal-org nova-test [--org-plan <slug>:<family>=<plan>] \\
        --reason "..." [--apply]                       # dry run unless --apply
    python -m app.services.billing.cli sweep-statuses [--apply]   # expire ended subscriptions; Q7 grace

All are safe to repeat. Commands that change accounts print what they would do unless `--apply` is
given, and write `platform_audit` rows (actor "operator command: <name>") when they apply.
"""
from __future__ import annotations

import argparse
import json

from app.db.session import SessionLocal
from app.models.platform import OrganizationSubscription
from app.services.billing import audit, backfill, catalogue, ledger, statuses


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


def _pairs(values: list[str], flag: str) -> dict[str, str]:
    result = {}
    for value in values:
        left, sep, right = value.partition("=")
        if not sep or not left or not right:
            raise SystemExit(f"{flag} expects KEY=PLAN, got {value!r}")
        result[left] = right
    return result


def run_backfill(db, args) -> dict:
    steps = backfill.plan(db, default_plans=_pairs(args.plan, "--plan"), internal_orgs=args.internal_org,
                          org_plans=_pairs(args.org_plan, "--org-plan"))
    counts: dict[str, int] = {}
    for step in steps:
        counts[step.action] = counts.get(step.action, 0) + 1
    report = {"mode": "apply" if args.apply else "dry-run", "counts": counts, "steps": [s.as_dict() for s in steps]}
    if args.apply:
        if not args.reason:
            raise SystemExit("--reason is required with --apply.")
        backfill.apply(db, steps, reason=args.reason, actor=audit.Actor.command("backfill-subscriptions"))
        db.commit()
        report["steps"] = [s.as_dict() for s in steps]
    else:
        db.rollback()
    return report


def run_sweep(db, args) -> dict:
    actions = statuses.sweep(db, apply=args.apply, actor=audit.Actor.command("sweep-statuses"))
    if args.apply:
        db.commit()
    else:
        db.rollback()
    return {"mode": "apply" if args.apply else "dry-run", "actions": actions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.services.billing.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed")
    commands.add_parser("grant-monthly")
    fill = commands.add_parser("backfill-subscriptions")
    fill.add_argument("--plan", action="append", default=[], help="FAMILY=PLAN_KEY default for a family")
    fill.add_argument("--internal-org", action="append", default=[], help="slug or ID that gets the Internal plan")
    fill.add_argument("--org-plan", action="append", default=[], help="ORG:FAMILY=PLAN_KEY for one organisation")
    fill.add_argument("--reason", default=None)
    fill.add_argument("--apply", action="store_true")
    sweep = commands.add_parser("sweep-statuses")
    sweep.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        if args.command == "seed":
            report = catalogue.seed_catalogue(db)
            db.commit()
            print(json.dumps({"plans": report.plans, "engine_links": report.engine_links, "prices": report.prices}))
        elif args.command == "grant-monthly":
            print(json.dumps(grant_monthly(db)))
        elif args.command == "backfill-subscriptions":
            try:
                print(json.dumps(run_backfill(db, args), indent=2))
            except backfill.BackfillError as exc:
                db.rollback()
                raise SystemExit(f"backfill refused: {exc}") from None
        else:
            print(json.dumps(run_sweep(db, args), indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
