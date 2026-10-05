"""Verify the NOVA staging topology without printing environment secrets."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, timeout: int = 30) -> tuple[bool, str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = (completed.stdout or completed.stderr).strip()
    return completed.returncode == 0, output


def http_get(url: str, *, expect: str | None = None) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            body = response.read().decode("utf-8", errors="replace")
            if response.status != 200:
                return False, f"HTTP {response.status}"
            if expect and expect not in body:
                return False, f"HTTP 200 but expected marker {expect!r} was absent"
            return True, f"HTTP {response.status}"
    except (urllib.error.URLError, TimeoutError) as exc:
        return False, str(exc)


def parse_ps(value: str) -> list[dict]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        return [json.loads(line) for line in value.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compose-file", default="docker-compose.gateway-test.yml")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    gateway = "gateway-test" in args.compose_file
    compose = ["docker", "compose", "-f", args.compose_file]
    services = (
        {
            "postgres": "postgis-gateway",
            "redis": "redis-gateway",
            "api": "api-gateway",
            "worker": "worker-gateway",
            "bff": "bff-gateway",
            "nginx": "nginx-gateway",
        }
        if gateway
        else {"postgres": "postgres", "redis": "redis", "api": "api", "worker": "worker", "bff": "bff", "nginx": "nginx"}
    )
    checks: list[tuple[str, bool, str]] = []

    ok, output = run([*compose, "config", "--quiet"])
    checks.append(("Compose configuration", ok, output or "valid"))

    ok, output = run([*compose, "ps", "--format", "json"])
    containers = parse_ps(output) if ok else []
    by_service = {item.get("Service"): item for item in containers}
    for label, service in services.items():
        item = by_service.get(service)
        state = str(item.get("State", "")) if item else "missing"
        health = str(item.get("Health", "")) if item else "missing"
        service_ok = state.lower() == "running" and health.lower() in {"healthy", ""}
        checks.append((f"{label} container", service_ok, f"state={state}, health={health or 'not-reported'}"))

    command_checks = [
        ("Nginx syntax", [*compose, "exec", "-T", services["nginx"], "nginx", "-t"]),
        (
            "API health",
            [*compose, "exec", "-T", services["api"], "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"],
        ),
        ("Worker ping", [*compose, "exec", "-T", services["worker"], "celery", "-A", "app.core.celery_app.celery_app", "inspect", "ping", "--timeout", "5"]),
        ("Redis ping", [*compose, "exec", "-T", services["redis"], "redis-cli", "ping"]),
        (
            "PostGIS readiness",
            [*compose, "exec", "-T", services["postgres"], "sh", "-c", 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
        ),
    ]
    for label, command in command_checks:
        ok, output = run(command, timeout=45)
        checks.append((label, ok, output.splitlines()[-1] if output else "no output"))

    base_url = args.base_url.rstrip("/")
    for label, path, marker in [
        ("Gateway health", "/healthz", "ok"),
        ("Frontend health", "/healthz/frontend", "NOVA GeoRisk"),
        ("BFF health", "/healthz/bff", None),
        ("Browser auth contract", "/auth/config", "configured"),
        ("React application", "/", "NOVA GeoRisk"),
    ]:
        ok, output = http_get(f"{base_url}{path}", expect=marker)
        checks.append((label, ok, output))

    print("NOVA STAGING HEALTH REPORT")
    for label, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}")
    failures = [label for label, ok, _ in checks if not ok]
    print(f"SUMMARY: {len(checks) - len(failures)} passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
