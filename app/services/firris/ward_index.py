"""Prebuilt, indexed ward file per approved dataset version (owner decision 2026-11-27, instead of a server upgrade).

Beside the approved GeoJSON in protected storage:
  <file>.wards-index.gpkg   ward features only (level = ward), the fields FRRIS uses, an R-tree spatial index
  <file>.wards-index.json   {"index_version", "dataset_sha256", "index_sha256", "features", "built_at"}

Every run, after the approval/readiness checks and the streamed SHA-256 of the approved GeoJSON (load_registered_source
with verify_only=True):
  * the sidecar's dataset_sha256 must equal the approved checksum and its index_version the current one;
  * the index file's own streamed SHA-256 must equal the sidecar's index_sha256;
  * only the features in the analysis area's bounding box are read (R-tree), then filtered by exact intersection.
A missing, stale or invalid index is rebuilt once from the verified GeoJSON in a short child process (its memory is
returned to the system before the Exposure computation starts). If that fails, WardIndexUnavailable is raised and the
caller shows no wards (fail closed); unapproved or changed data is never used.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

INDEX_VERSION = 1
INDEX_SUFFIX, META_SUFFIX = ".wards-index.gpkg", ".wards-index.json"
LAYER = "wards"
COLUMNS = ("spatial_unit_id", "name", "level", "council_short", "council_name", "region_name", "provenance_status")
BUILD_TIMEOUT_S = 600
APP_ROOT = Path(__file__).resolve().parents[3]


class WardIndexUnavailable(RuntimeError):
    """The ward index could not be verified or built; wards are not shown for this run."""


def paths(source: Path) -> tuple[Path, Path]:
    return source.with_name(source.name + INDEX_SUFFIX), source.with_name(source.name + META_SUFFIX)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verified(source: Path, dataset_sha256: str) -> Path | None:
    """The index path when its sidecar matches the approved dataset and its bytes match the sidecar; else None."""
    index, meta = paths(source)
    try:
        record = json.loads(meta.read_text(encoding="utf-8"))
        if (record.get("index_version") != INDEX_VERSION or record.get("dataset_sha256") != dataset_sha256.lower()
                or not index.is_file() or sha256_file(index) != record.get("index_sha256")):
            return None
        return index
    except (OSError, ValueError, AttributeError):
        return None


def build(source: Path, dataset_sha256: str) -> dict:
    """Write the index and its sidecar atomically. The caller has verified the source bytes against the approval."""
    import pyogrio
    if sha256_file(source) != dataset_sha256.lower():  # never index bytes other than the approved version
        raise WardIndexUnavailable("The dataset bytes changed before the ward index was built.")
    index, meta = paths(source)
    available = set(pyogrio.read_info(source)["fields"])
    frame = pyogrio.read_dataframe(source, columns=[c for c in COLUMNS if c in available])
    frame = frame[frame["level"].astype(str).str.strip().str.lower() == "ward"]
    if frame.empty:
        raise WardIndexUnavailable("The approved dataset has no ward-level features.")
    tmp_index = index.with_name(f".{index.name}.{os.getpid()}.tmp.gpkg")
    tmp_meta = meta.with_name(f".{meta.name}.{os.getpid()}.tmp")
    try:
        pyogrio.write_dataframe(frame, tmp_index, layer=LAYER, driver="GPKG", spatial_index=True)
        os.chmod(tmp_index, 0o600)
        record = {"index_version": INDEX_VERSION, "dataset_sha256": dataset_sha256.lower(), "index_sha256": sha256_file(tmp_index),
                  "features": int(len(frame)), "built_at": datetime.now(timezone.utc).isoformat()}
        tmp_meta.write_text(json.dumps(record), encoding="utf-8")
        os.chmod(tmp_meta, 0o600)
        tmp_index.replace(index)
        tmp_meta.replace(meta)  # the sidecar last: a reader never sees a sidecar for a half-written index
        return record
    finally:
        tmp_index.unlink(missing_ok=True)
        tmp_meta.unlink(missing_ok=True)


def ensure(source: Path, dataset_sha256: str) -> Path:
    """A verified index for the approved version, building it once in a child process when needed."""
    index = verified(source, dataset_sha256)
    if index is not None:
        return index
    started = time.monotonic()
    try:
        done = subprocess.run([sys.executable, "-m", "app.services.firris.ward_index", "build", str(source), dataset_sha256],
                              cwd=APP_ROOT, capture_output=True, text=True, timeout=BUILD_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise WardIndexUnavailable("The ward index took too long to build for this run.") from exc
    index = verified(source, dataset_sha256)
    if done.returncode != 0 or index is None:
        reason = (done.stderr.strip().splitlines() or ["unknown error"])[-1][:300]
        raise WardIndexUnavailable(f"The ward index could not be built ({reason}).")
    import logging
    logging.getLogger(__name__).info("ward index built for %s in %.1f s", source.name, time.monotonic() - started)
    return index


def read_touching(index: Path, aoi) -> list[dict]:
    """Ward rows whose geometry intersects ``aoi`` (shapely), read through the R-tree by bounding box."""
    import pyogrio
    frame = pyogrio.read_dataframe(index, layer=LAYER, bbox=tuple(aoi.bounds))
    rows = []
    for row in frame.itertuples(index=False):
        if row.geometry is not None and row.geometry.intersects(aoi):
            rows.append(row._asdict())
    return rows


if __name__ == "__main__":  # python -m app.services.firris.ward_index build <source> <sha256>
    if len(sys.argv) != 4 or sys.argv[1] != "build":
        raise SystemExit("usage: python -m app.services.firris.ward_index build <source> <sha256>")
    print(json.dumps(build(Path(sys.argv[2]), sys.argv[3])))
