"""Fail-closed production-image gate, including files hidden by later layers.

Run on the Docker host: python scripts/check_image_packaging.py IMAGE.
Only paths, rule names and hashes are reported, never file contents. The small
reviewed dependency exception inventory binds public certificates/parser source
literals to exact bytes; it cannot exempt application paths or changed files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile

POLICY = Path(__file__).with_name("docker_packaging_exceptions.json")
KEY_MARKER = re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
SERVICE_ACCOUNT = re.compile(rb'"type"\s*:\s*"service_account"')
PRIVATE_DIRS = {
    "secrets", "artifacts", "data", "datasets", "raw-data", "private-data",
    "docx-files", "docker-data", ".git", ".aws", ".ssh", ".venv", ".codex", ".agents",
}
# /app/outputs is the empty runtime mount point; files beneath it are forbidden.
APP_ROOTS = {"app", "scripts", "requirements.txt", "alembic.ini", "outputs"}
ADMIN_SCRIPTS = {
    "admin_entitlements.py", "admin_identity.py", "reconcile_legacy_projects.py",
    "validate_production_environment.py",
}


def path_rules(name: str, *, is_file: bool = True) -> set[str]:
    path = PurePosixPath(name.removeprefix("./").lstrip("/"))
    parts = tuple(part.lower() for part in path.parts)
    if ".." in parts:
        return {"unsafe-path"}
    base = parts[-1] if parts else ""
    rules = set()
    # System libraries legitimately contain directories named data (GDAL etc.).
    # Private-data directory names are forbidden in application/work directories.
    application = parts and parts[0] not in {"usr", "etc", "lib", "lib64", "var", "bin", "sbin"}
    if application and any(p in PRIVATE_DIRS for p in parts):
        rules.add("private-path")
    if application and "outputs" in parts and parts != ("app", "outputs"):
        rules.add("runtime-output")
    if base == ".env" or base.startswith(".env."):
        rules.add("dotenv")
    if base == "cookies.txt":
        rules.add("cookies")
    if is_file and (any(word in base for word in ("credential", "secret", "service_account"))):
        rules.add("credential-name")
    if is_file and path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        rules.add("key-container")
    if parts and parts[0] == "app":
        if len(parts) > 1 and parts[1] not in APP_ROOTS:
            rules.add("non-runtime-path")
        if len(parts) > 2 and parts[1] == "outputs" and is_file:
            rules.add("runtime-output")
        if len(parts) > 2 and parts[1] == "scripts" and is_file and parts[2] not in ADMIN_SCRIPTS:
            rules.add("non-runtime-script")
        if is_file and any(p in {"tests", "fixtures", "__pycache__", ".pytest_cache"} for p in parts):
            rules.add("test-or-cache")
    return rules


def inspect_bytes(source, initial_rules=(), *, is_json=False, pyc=False):
    """Bounded streaming inspection; overlap catches markers at chunk boundaries."""
    digest = hashlib.sha256()
    rules = set(initial_rules)
    tail = b""
    json_chunks = []
    json_size = 0
    hash_skip = 16 if pyc else 0
    while chunk := source.read(1024 * 1024):
        # CPython's 16-byte header includes installation timestamps. Bind the
        # entire code body, while still scanning the header for secret markers.
        digest.update(chunk[hash_skip:])
        hash_skip = max(0, hash_skip - len(chunk))
        window = tail + chunk
        if b"PRIVATE KEY" in window and KEY_MARKER.search(window):
            rules.add("private-key-marker")
        if b"service_account" in window and SERVICE_ACCOUNT.search(window):
            rules.add("service-account-json")
        if is_json:
            json_size += len(chunk)
            if json_size <= 32 * 1024 * 1024:
                json_chunks.append(chunk)
        tail = window[-8192:]
    if is_json:
        if json_size > 32 * 1024 * 1024:
            rules.add("uninspectable-json")
        else:
            try:
                pending = [json.loads(b"".join(json_chunks))]
            except (ValueError, UnicodeError):
                rules.add("uninspectable-json")
                pending = []
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    if value.get("type") == "service_account":
                        rules.add("service-account-json")
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
                elif isinstance(value, str):
                    decoded = value.encode()
                    if KEY_MARKER.search(decoded):
                        rules.add("private-key-marker")
                    if SERVICE_ACCOUNT.search(decoded):
                        rules.add("service-account-json")
    return rules, digest.hexdigest()


def load_exceptions(path=POLICY):
    policy = json.loads(Path(path).read_text())
    exceptions = {}
    for entry in policy:
        name = entry["path"]
        # Exceptions can only describe immutable OS/dependency artifacts, never
        # application files, home directories or credential mount locations.
        if not name.startswith(("usr/", "etc/ssl/certs/")):
            raise ValueError("Dependency exception outside permitted system paths")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) or not entry["reason"]:
            raise ValueError("Invalid dependency exception")
        if not set(entry['rules']) <= {'credential-name', 'key-container', 'private-key-marker'}:
            raise ValueError('Credential JSON and unsafe paths cannot be excepted')
        exceptions[(name, entry["sha256"])] = set(entry["rules"])
    return exceptions


def scan_tar(archive, exceptions=None):
    """Inspect every regular file/link in a filesystem or an individual layer."""
    exceptions = exceptions or {}
    findings = []
    files = 0
    exempted = 0
    for member in archive:
        name = member.name.removeprefix("./").lstrip("/")
        if not name or PurePosixPath(name).name.startswith(".wh."):
            continue
        rules = path_rules(name, is_file=member.isfile() or member.issym() or member.islnk())
        if member.isfile():
            files += 1
            with archive.extractfile(member) as source:
                rules, digest = inspect_bytes(source, rules, is_json=name.lower().endswith('.json'), pyc=name.endswith('.pyc'))
            allowed = exceptions.get((name, digest), set())
            exempted += bool(rules & allowed)
            rules -= allowed
        else:
            digest = None
            if member.issym() or member.islnk():
                # Resolve relative library/CA symlinks inside the image root;
                # ordinary ../lib targets are not archive path traversal.
                target = posixpath.normpath(posixpath.join(posixpath.dirname('/' + name), member.linkname)).lstrip('/')
                rules |= path_rules(target)
                # Public CA links are content-checked at their target file.
                if name.startswith(("etc/ssl/certs/", "usr/lib/ssl/")) and "key-container" in rules:
                    if target.startswith(("etc/ssl/certs/", "usr/share/ca-certificates/")):
                        rules.discard("key-container")
        if rules:
            findings.append({"path": name, "rules": sorted(rules), "sha256": digest})
    return findings, files, exempted


def scan_image(image: str, exceptions=None):
    image_id = subprocess.check_output(["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True).strip()
    # Docker save exposes *every* layer, including deleted/overwritten files.
    # Never extract untrusted archive paths onto the host filesystem.
    with tempfile.TemporaryFile() as saved:
        subprocess.run(["docker", "image", "save", image_id], stdout=saved, check=True)
        saved.seek(0)
        with tarfile.open(fileobj=saved, mode="r:") as outer:
            manifest = json.load(outer.extractfile("manifest.json"))
            if len(manifest) != 1 or not manifest[0].get("Layers"):
                raise ValueError("Expected exactly one image with inspectable layers")
            findings, file_count, exempted = [], 0, 0
            for index, layer in enumerate(manifest[0]["Layers"]):
                with outer.extractfile(layer) as stream, tarfile.open(fileobj=stream, mode="r|*") as archive:
                    hits, count, allowed = scan_tar(archive, exceptions)
                    file_count += count
                    exempted += allowed
                    findings.extend({**hit, "layer": index} for hit in hits)
            # Config metadata is also recoverable from the distributed image.
            config = outer.extractfile(manifest[0]["Config"])
            rules, _ = inspect_bytes(config, is_json=True)
            if rules:
                findings.append({"path": "<image-config>", "rules": sorted(rules)})
    return {"image_id": image_id, "layers": len(manifest[0]["Layers"]), "files_checked": file_count,
            "reviewed_dependency_matches": exempted, "findings": findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--inventory", action="store_true", help="Show candidates without applying reviewed dependency exceptions")
    args = parser.parse_args()
    try:
        result = scan_image(args.image, {} if args.inventory else load_exceptions())
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
        # Avoid including subprocess output/archive payloads in error logs.
        raise SystemExit("Image packaging scan could not complete; gate FAILED")
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(bool(result["findings"]))


if __name__ == "__main__":
    main()
