"""Operator commands, run inside the API container (docs/ABLINER_PAYMENTS_PLAN.md §5):

    python -m app.services.abliner.cli reconcile [--apply]   # cron every 10 minutes with --apply (flock, log)
    python -m app.services.abliner.cli test-payment --subscription-id <id> --admin-email <NOVA ARI admin> \
        --operator "<name>" [--apply]                         # the owner's TZS 500 live test: no credits

test-payment asks for the phone number at a prompt (so it stays out of the shell history) unless --phone is given,
and never prints it. Without --apply it only shows what it would do.

Prints JSON counts only: no phone numbers, no payloads, no secrets.
"""
from __future__ import annotations

import argparse
import json
import uuid

from app.db.session import SessionLocal
from app.core.http import PublicAPIError
from app.models.identity import User
from app.models.platform import OrganizationSubscription
from app.services.abliner import intents, reconcile
from app.services.abliner.client import get_client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.services.abliner.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("reconcile")
    run.add_argument("--apply", action="store_true")
    test = commands.add_parser("test-payment")
    test.add_argument("--subscription-id", required=True, type=uuid.UUID)
    test.add_argument("--admin-email", required=True)
    test.add_argument("--operator", required=True)
    test.add_argument("--phone", help="optional; otherwise asked at a prompt")
    test.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        if args.command == "reconcile":
            report = reconcile.run(db, get_client(), apply=args.apply)
            print(json.dumps({"mode": report.mode, "checked": report.checked, "outcomes": report.counts}))
            return 0
        return _test_payment(db, args)
    finally:
        db.close()


def _test_payment(db, args, *, ask=input, client=None) -> int:
    subscription = db.get(OrganizationSubscription, args.subscription_id)
    admin = db.query(User).filter(User.email.ilike(args.admin_email.strip())).one_or_none()
    plan = {"subscription_id": str(args.subscription_id), "organization_id": str(subscription.organization_id) if subscription else None,
            "amount_tzs": intents.TEST_AMOUNT, "credits": 0, "admin_found": admin is not None}
    if not args.apply:
        print(json.dumps({"mode": "dry-run", **plan}))
        return 0
    if subscription is None or admin is None:
        raise SystemExit("test-payment refused: subscription or admin user not found")
    phone_number = args.phone or ask("Phone number for the TZS 500 test (not shown again): ")
    try:
        intent = intents.create_test(db, admin_user_id=admin.id, subscription_id=subscription.id, phone_number=phone_number,
                                     operator=args.operator, client=client or get_client())
    except PublicAPIError as exc:
        raise SystemExit(f"test-payment refused: {exc.code}") from None
    print(json.dumps({"mode": "apply", "intent_id": str(intent.id), "reference": intent.reference, "status": intent.status,
                      "phone": intent.phone_masked, "next": "approve on the phone, then check the webhook and the payment"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
