"""Validation for the filesystem artifact backend shared by API and workers."""
from __future__ import annotations

import os
from pathlib import Path

from app.core.config import get_settings


class ArtifactStorageError(RuntimeError):
    pass


def artifact_root() -> Path:
    settings = get_settings()
    if settings.artifact_storage_backend.strip().lower() != "filesystem":
        raise ArtifactStorageError("Unsupported artifact storage backend.")
    return Path(settings.output_storage_dir).resolve()


def require_artifact_storage_ready() -> Path:
    """Create the configured root and require process-level read/write access."""
    root = artifact_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ArtifactStorageError("Artifact storage root cannot be created.") from exc
    if not root.is_dir() or not os.access(root, os.R_OK | os.W_OK | os.X_OK):
        raise ArtifactStorageError("Artifact storage root is not readable and writable.")
    return root
