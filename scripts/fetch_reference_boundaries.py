"""Fetch the pinned boundary files listed in app/reference_data/boundaries/<country>/manifest.json and verify SHA-256.

    python scripts/fetch_reference_boundaries.py TZA <target_dir>

The files are release artifacts (not in git, not downloaded at run time). A checksum mismatch stops with an error and
keeps nothing, so a changed upstream file can never be used silently.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app" / "reference_data" / "boundaries"


def main(country: str, target: str) -> None:
    manifest = json.loads((ROOT / country.lower() / "manifest.json").read_text())
    out = Path(target)
    out.mkdir(parents=True, exist_ok=True)
    for key, entry in manifest["files"].items():
        data = urllib.request.urlopen(entry["url"], timeout=120).read()  # noqa: S310 - pinned public release URL
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry["sha256"]:
            raise SystemExit(f"{key}: SHA-256 {digest} does not match the manifest {entry['sha256']}; nothing written")
        (out / entry["file"]).write_bytes(data)
        print(f"{key}: {entry['file']} ({len(data):,} bytes) verified")


if __name__ == "__main__":
    main(*sys.argv[1:3])
