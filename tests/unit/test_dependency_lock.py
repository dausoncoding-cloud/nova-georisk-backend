"""The production image installs exactly the hash-locked package set (no transitive drift on rebuild)."""
import re
from pathlib import Path

from scripts.verify_docker_packaging import BASE_IMAGE_TOOLS, lock_mismatches, parse_lock

ROOT = Path(__file__).resolve().parents[2]
LOCK = (ROOT / "requirements.lock").read_text()


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def test_every_locked_package_is_exactly_pinned_with_hashes():
    entries = re.split(r"\n(?=[A-Za-z0-9])", "\n".join(l for l in LOCK.splitlines() if not l.startswith("#")).strip())
    assert len(entries) > 100
    for entry in entries:
        assert re.match(r"^[A-Za-z0-9_.-]+==[^\s\;]+ \\", entry), entry.splitlines()[0]
        assert "--hash=sha256:" in entry, entry.splitlines()[0]


def test_direct_pins_in_requirements_match_the_lock():
    locked = parse_lock(LOCK)
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            name, pinned = line.split("==")
            base = _norm(name.split("[")[0])
            assert locked.get(base) == pinned.strip(), (name, pinned, locked.get(base))


def test_lock_keeps_the_versions_that_fixed_production():
    locked = parse_lock(LOCK)
    assert locked["kombu"] == "5.6.2" and locked["redis"] == "5.0.8" and locked["celery"] == "5.4.0"


def test_docker_build_installs_only_from_the_hash_lock():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "pip install --no-cache-dir --require-hashes --no-deps -r requirements.lock" in dockerfile
    assert "-r requirements.txt" not in dockerfile
    assert "!requirements.lock" in (ROOT / ".dockerignore").read_text()


def test_packaging_gate_rejects_anything_outside_the_lock():
    lock = "a==1.0 \\\n    --hash=sha256:" + "0" * 64 + "\nb==2.0 \\\n    --hash=sha256:" + "1" * 64 + "\n"
    assert lock_mismatches("a==1.0\nb==2.0\npip==24.0\nwheel==0.46.3\n", lock) == []
    assert lock_mismatches("a==1.0\nb==2.1\n", lock) == ["b: image 2.1, lock 2.0"]
    assert lock_mismatches("a==1.0\nb==2.0\nc==3.0\n", lock) == ["c: image 3.0, not in lock"]
    assert lock_mismatches("a==1.0\n", lock) == ["b: in lock 2.0, missing from image"]
    assert BASE_IMAGE_TOOLS == {"pip", "wheel"}
