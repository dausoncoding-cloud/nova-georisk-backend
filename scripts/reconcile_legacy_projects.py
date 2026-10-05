"""Reassign explicitly selected legacy projects to one validated organization."""
from __future__ import annotations

import argparse
import json
import uuid

from app.db.session import SessionLocal
from app.models.identity import LEGACY_ORGANIZATION_ID, Organization
from app.models.project import Project


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-organization-id", required=True, type=uuid.UUID)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--project-id", action="append", type=uuid.UUID)
    selector.add_argument("--all-legacy", action="store_true")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Apply the validated mapping; omission is a dry-run.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.target_organization_id == LEGACY_ORGANIZATION_ID:
        raise SystemExit("Target must not be the legacy organization.")
    if args.project_id and len(set(args.project_id)) != len(args.project_id):
        raise SystemExit("Duplicate project IDs are ambiguous; no changes committed.")

    with SessionLocal() as db:
        target = db.get(Organization, args.target_organization_id)
        if target is None:
            raise SystemExit("Target organization does not exist; no changes committed.")
        query = db.query(Project).filter(Project.organization_id == LEGACY_ORGANIZATION_ID)
        legacy_count = query.count()
        if args.all_legacy:
            projects = query.order_by(Project.id).all()
        else:
            requested = set(args.project_id or [])
            projects = query.filter(Project.id.in_(requested)).order_by(Project.id).all()
            resolved = {project.id for project in projects}
            unresolved = requested - resolved
            if unresolved:
                rendered = ", ".join(str(item) for item in sorted(unresolved, key=str))
                raise SystemExit(
                    "Every selected project must exist and currently belong to the legacy "
                    f"organization. Unresolved: {rendered}. No changes committed."
                )
        if not projects:
            raise SystemExit("No legacy projects matched; no changes committed.")

        summary = {
            "mode": "commit" if args.commit else "dry-run",
            "legacy_project_count": legacy_count,
            "selected_project_count": len(projects),
            "target_organization": {"id": str(target.id), "name": target.name},
            "projects": [{"id": str(project.id), "name": project.name} for project in projects],
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        if not args.commit:
            db.rollback()
            print("DRY RUN: no database changes committed.")
            return
        for project in projects:
            old_organization_id = project.organization_id
            project.organization_id = target.id
            print(
                json.dumps(
                    {
                        "event": "legacy_project_reassigned",
                        "project_id": str(project.id),
                        "from_organization_id": str(old_organization_id),
                        "to_organization_id": str(target.id),
                    },
                    sort_keys=True,
                )
            )
        db.commit()
        print(f"COMMITTED: reassigned {len(projects)} project(s).")


if __name__ == "__main__":
    main()
