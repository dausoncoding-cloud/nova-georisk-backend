#!/usr/bin/env python3
"""Enter the Abliner API key and webhook signing secret into the live compose file (billing phase 1, step 6).

Run by the OWNER only, as `deploy`, in an interactive SSH session (ssh -t). Values are typed or pasted at hidden
prompts (getpass: no echo, not in shell history, not in any process's argv). Nothing here prints, logs or returns
a value. Only the api and worker services get them (the BFF and gateway never need them).

    python3 set_abliner_secrets.py --check      # read-only: what would change, no prompts
    python3 set_abliner_secrets.py              # prompts twice for each value, then writes

What it writes: in /home/deploy/nova-releases/firris-2f1b2dc/compose.active.json, the `environment` lists of
firris-2f1b2dc-api and firris-2f1b2dc-worker get ABLINER_API_KEY=<key> and ABLINER_WEBHOOK_SECRET=<secret>
(replacing earlier ones). First a copy compose.active.json.before-abliner-<UTC stamp> (mode 600). The new file is
written to a temporary file (mode 600, same folder), flushed to disk, then renamed over the old one. Afterwards the
file is re-read and compared with the copy: only those two names in those two services may differ.
It refuses if ABLINER_PAYMENTS_ENABLED is set to anything but false, if the file is not mode 600 or not owned by
the current user, or if the api/worker images in the file differ from the running containers.
It does NOT restart anything.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

COMPOSE = "/home/deploy/nova-releases/firris-2f1b2dc/compose.active.json"
PROJECT = "firris-release-2f1b2dc"
SERVICES = ("firris-2f1b2dc-api", "firris-2f1b2dc-worker")
NAMES = {"ABLINER_API_KEY": "tsl_live_", "ABLINER_WEBHOOK_SECRET": "whsec_"}


def fail(message: str) -> None:
    print("REFUSED: " + message)
    sys.exit(1)


def env_names(service: dict) -> list[str]:
    env = service.get("environment") or []
    if not isinstance(env, list):
        fail("environment is not a list; this script expects the list form")
    return [item.split("=", 1)[0] for item in env]


def ask(name: str, prefix: str) -> str:
    first = getpass.getpass(f"{name} (hidden, starts with {prefix}): ")
    second = getpass.getpass(f"{name} again: ")
    if first != second:
        fail(f"the two entries for {name} differ (nothing written)")
    value = first.strip()
    if value != first or any(ch.isspace() for ch in value):
        fail(f"{name} contains spaces or line breaks (nothing written)")
    if not value.startswith(prefix) or not 16 <= len(value) <= 512:
        fail(f"{name} does not look right: it must start with {prefix} (nothing written)")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="read-only: show what would change")
    parser.add_argument("--compose", default=COMPOSE)
    parser.add_argument("--skip-container-check", action="store_true", help=argparse.SUPPRESS)  # local tests only
    args = parser.parse_args()
    os.umask(0o077)

    info = os.stat(args.compose)
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
        fail("the compose file must be mode 600 and owned by you")
    with open(args.compose, encoding="utf-8") as handle:
        compose = json.load(handle)
    services = compose.get("services") or {}
    for name in SERVICES:
        if name not in services:
            fail(f"service {name} is missing")
    for name, service in services.items():
        for item in service.get("environment") or []:
            key, _, value = item.partition("=")
            if key == "ABLINER_PAYMENTS_ENABLED" and value.strip().lower() not in {"", "false", "0"}:
                fail(f"ABLINER_PAYMENTS_ENABLED is on in {name}; this step is for flags OFF only")
    if not args.skip_container_check:
        for name in SERVICES:
            running = subprocess.run(
                ["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}",
                 "--filter", f"label=com.docker.compose.service={name}"], capture_output=True, text=True).stdout.split()
            if len(running) != 1:
                fail(f"expected one running {name} container, found {len(running)}")
            image = subprocess.run(["docker", "inspect", "-f", "{{.Image}}", running[0]],
                                   capture_output=True, text=True).stdout.strip()
            if image != services[name].get("image"):
                fail(f"{name}: the running image differs from the compose file; stop and ask")

    present = {name: [n for n in NAMES if n in env_names(services[name])] for name in SERVICES}
    print("compose file:", args.compose)
    for name in SERVICES:
        print(f"  {name}: will set {', '.join(NAMES)}" + (f" (replacing existing {', '.join(present[name])})" if present[name] else ""))
    others = [n for n in services if n not in SERVICES and any(k in env_names(services[n]) for k in NAMES)]
    if others:
        fail("Abliner values found in other services: " + ", ".join(others))
    if args.check:
        print("CHECK ONLY: nothing written")
        return 0

    values = {name: ask(name, prefix) for name, prefix in NAMES.items()}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = os.path.dirname(os.path.abspath(args.compose))
    backup = f"{args.compose}.before-abliner-{stamp}"
    with open(args.compose, "rb") as src:
        original = src.read()
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as dst:
        dst.write(original)
        dst.flush()
        os.fsync(dst.fileno())

    for name in SERVICES:
        env = [item for item in services[name]["environment"] if item.split("=", 1)[0] not in NAMES]
        env += [f"{key}={value}" for key, value in values.items()]
        services[name]["environment"] = env
    fd, temp = tempfile.mkstemp(prefix=".compose.active.", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(compose, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, args.compose)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise
    directory = os.open(folder, os.O_RDONLY)
    os.fsync(directory)
    os.close(directory)
    values.clear()

    with open(args.compose, encoding="utf-8") as handle:
        after = json.load(handle)
    before = json.loads(original)
    for name in SERVICES:
        kept = lambda env: [item for item in env if item.split("=", 1)[0] not in NAMES]  # noqa: E731
        if kept(after["services"][name]["environment"]) != kept(before["services"][name].get("environment") or []):
            fail(f"unexpected change in {name}; restore {backup}")
        if sorted(n for n in env_names(after["services"][name]) if n in NAMES) != sorted(NAMES):
            fail(f"{name} does not have both values; restore {backup}")
        after["services"][name] = before["services"][name] = None
    if after != before:
        fail(f"something other than the api/worker environment changed; restore {backup}")
    mode = stat.S_IMODE(os.stat(args.compose).st_mode)
    print(f"OK: api and worker have ABLINER_API_KEY and ABLINER_WEBHOOK_SECRET (values not shown); "
          f"file mode {mode:o}; copy of the previous file: {backup}")
    print("Next: restart api and worker only (see the procedure). Nothing was restarted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
