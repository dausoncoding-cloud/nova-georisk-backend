"""Deploy-time command: the only way to grant or revoke the NOVA ARI admin role. Run inside the API container
by someone with server access:

    python -m app.services.platform_admin.cli grant  --email person@novarex.example --operator "<your name>" --reason "..."
    python -m app.services.platform_admin.cli revoke --email person@novarex.example --operator "<your name>" --reason "..."
    python -m app.services.platform_admin.cli list

The person must have signed in once (so their user exists). Each grant and revoke is written to
platform_audit with the operator's name and the reason.
"""
from __future__ import annotations

import argparse
import json
import uuid

from app.db.session import SessionLocal
from app.models.identity import User
from app.models.platform_admin import PlatformAdmin
from app.services.platform_admin import access


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.services.platform_admin.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("grant", "revoke"):
        command = commands.add_parser(name)
        who = command.add_mutually_exclusive_group(required=True)
        who.add_argument("--email")
        who.add_argument("--user-id", type=uuid.UUID)
        command.add_argument("--operator", required=True, help="who is running this command")
        command.add_argument("--reason", required=True)
    commands.add_parser("list")
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        if args.command == "list":
            rows = (db.query(PlatformAdmin, User).join(User, User.id == PlatformAdmin.user_id)
                    .filter(PlatformAdmin.revoked_at.is_(None)).order_by(PlatformAdmin.granted_at).all())
            print(json.dumps([{"user_id": str(user.id), "email": user.email, "name": user.display_name,
                               "granted_at": row.granted_at.isoformat(), "granted_by": row.granted_by}
                              for row, user in rows], indent=2))
            return 0
        action = access.grant if args.command == "grant" else access.revoke
        try:
            row = action(db, email=args.email, user_id=args.user_id, reason=args.reason, operator=args.operator)
        except (access.GrantError, ValueError) as exc:
            db.rollback()
            raise SystemExit(f"{args.command} refused: {exc}") from None
        db.commit()
        print(json.dumps({"command": args.command, "user_id": str(row.user_id)}))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
