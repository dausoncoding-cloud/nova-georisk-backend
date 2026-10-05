"""Dry-run-first administration of organization engine entitlements."""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.identity import Organization, User
from app.models.platform import Engine, EntitlementStatus, OrganizationEngineEntitlement


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamps must include a UTC offset.")
    return parsed.astimezone(timezone.utc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization-id", required=True, type=uuid.UUID)
    parser.add_argument("--engine-key", required=True)
    parser.add_argument("--status", required=True, choices=[item.value for item in EntitlementStatus])
    parser.add_argument("--source", required=True)
    parser.add_argument("--starts-at", type=_timestamp)
    parser.add_argument("--ends-at", type=_timestamp)
    parser.add_argument("--trial-ends-at", type=_timestamp)
    parser.add_argument("--external-subscription-id")
    parser.add_argument("--granted-by-user-id", type=uuid.UUID)
    parser.add_argument("--commit", action="store_true", help="Apply after reviewing the dry-run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    engine_key = args.engine_key.strip().lower()
    if args.status == EntitlementStatus.TRIAL.value and args.trial_ends_at is None:
        raise SystemExit("Trial entitlements require --trial-ends-at; no changes committed.")
    if args.ends_at and args.starts_at and args.ends_at <= args.starts_at:
        raise SystemExit("--ends-at must be later than --starts-at; no changes committed.")

    with SessionLocal() as db:
        organization = db.get(Organization, args.organization_id)
        engine = db.get(Engine, engine_key)
        if organization is None:
            raise SystemExit("Organization not found; no changes committed.")
        if engine is None:
            raise SystemExit("Engine is not registered; no changes committed.")
        if args.granted_by_user_id is not None and db.get(User, args.granted_by_user_id) is None:
            raise SystemExit("Granting user not found; no changes committed.")

        entitlement = (
            db.query(OrganizationEngineEntitlement)
            .filter(
                OrganizationEngineEntitlement.organization_id == organization.id,
                OrganizationEngineEntitlement.engine_key == engine.key,
            )
            .one_or_none()
        )
        previous = None
        if entitlement is None:
            entitlement = OrganizationEngineEntitlement(
                organization_id=organization.id,
                engine_key=engine.key,
                status=EntitlementStatus(args.status),
                source=args.source,
            )
            action = "create"
        else:
            action = "update"
            previous = {
                "status": entitlement.status.value,
                "source": entitlement.source,
                "starts_at": entitlement.starts_at.isoformat() if entitlement.starts_at else None,
                "ends_at": entitlement.ends_at.isoformat() if entitlement.ends_at else None,
                "trial_ends_at": (
                    entitlement.trial_ends_at.isoformat() if entitlement.trial_ends_at else None
                ),
            }
        entitlement.status = EntitlementStatus(args.status)
        entitlement.source = args.source
        entitlement.starts_at = args.starts_at
        entitlement.ends_at = args.ends_at
        entitlement.trial_ends_at = args.trial_ends_at
        entitlement.external_subscription_id = args.external_subscription_id
        entitlement.granted_by_user_id = args.granted_by_user_id
        db.add(entitlement)

        event = {
            "event": "engine_entitlement_change",
            "mode": "commit" if args.commit else "dry-run",
            "action": action,
            "organization": {"id": str(organization.id), "name": organization.name},
            "engine": {"key": engine.key, "name": engine.name},
            "previous": previous,
            "proposed": {
                "status": entitlement.status.value,
                "source": entitlement.source,
                "starts_at": entitlement.starts_at.isoformat() if entitlement.starts_at else None,
                "ends_at": entitlement.ends_at.isoformat() if entitlement.ends_at else None,
                "trial_ends_at": (
                    entitlement.trial_ends_at.isoformat() if entitlement.trial_ends_at else None
                ),
                "granted_by_user_id": (
                    str(entitlement.granted_by_user_id) if entitlement.granted_by_user_id else None
                ),
            },
        }
        print(json.dumps(event, indent=2, sort_keys=True))
        if not args.commit:
            db.rollback()
            print("DRY RUN: no entitlement changes committed.")
            return
        db.commit()
        print("COMMITTED: entitlement change applied; retain the JSON event in the audit log.")


if __name__ == "__main__":
    main()
