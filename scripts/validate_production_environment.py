"""Fail closed on production configuration without printing secret values."""
from __future__ import annotations

import sys

from pydantic import ValidationError

from app.core.config import Settings


def main() -> int:
    try:
        settings = Settings()
    except ValidationError as exc:
        print("NOVA PRODUCTION ENVIRONMENT: FAILED", file=sys.stderr)
        for error in exc.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in error["loc"]) or "configuration"
            print(f"- {location}: {error['msg']}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print("NOVA PRODUCTION ENVIRONMENT: FAILED", file=sys.stderr)
        print(f"- configuration: {exc}", file=sys.stderr)
        return 1

    if settings.app_env.strip().lower() != "production":
        print("NOVA PRODUCTION ENVIRONMENT: FAILED", file=sys.stderr)
        print("- APP_ENV must be production for this deployment gate.", file=sys.stderr)
        return 1

    checks = {
        "debug disabled": not settings.debug,
        "secure session cookie": settings.session_cookie_secure,
        "OIDC configured": settings.oidc_is_configured,
        "first-user bootstrap disabled": not settings.oidc_bootstrap_first_user_enabled,
        "public outputs disabled": not settings.public_outputs_enabled,
        "public API docs disabled": not settings.expose_api_docs,
        "filesystem artifacts configured": settings.artifact_storage_backend == "filesystem",
        "worker hard limit exceeds soft limit": (
            settings.celery_task_time_limit_seconds
            > settings.celery_task_soft_time_limit_seconds
        ),
    }
    failed = [label for label, passed in checks.items() if not passed]
    print("NOVA PRODUCTION ENVIRONMENT")
    for label, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}  {label}")
    print(
        "PASS  configured CORS origins: "
        f"{len(settings.allowed_cors_origins)} (same-origin deployments may use zero)"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
