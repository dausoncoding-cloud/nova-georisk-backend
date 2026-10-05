# NOVA artifact storage contract

## Supported production topology

The currently supported backend is `ARTIFACT_STORAGE_BACKEND=filesystem`. In production,
`OUTPUT_STORAGE_DIR` must be an absolute path. The supplied Compose topology uses
`/app/outputs` and mounts the same durable `nova_artifacts` volume into the API and Celery
worker containers.

- Workers are the primary artifact writers.
- The API is the authorized artifact reader and may also write legacy synchronous exports.
- The BFF and Nginx never mount the artifact volume.
- The artifact directory is not a static/public web root.
- Downloads are served only by authorization-checked result endpoints.

The application image runs as the unprivileged `nova` user. API and worker health checks
fail when the configured artifact root cannot be created or is not readable and writable.

## Database and filesystem boundary

`Result.output_files` is the authoritative artifact manifest. Stored paths must be relative
to `OUTPUT_STORAGE_DIR`; absolute filesystem paths are never returned to clients. Retrieval
resolves the relative path beneath the configured root and rejects traversal outside it.

An artifact becomes public to authorized callers only after its Result manifest is committed.
A worker crash before that commit can leave an unreferenced file, but cannot expose it through
the API. Automated orphan cleanup is not implemented and must not delete files without first
checking live Result references.

## Durability and operations

- Back up PostGIS and `nova_artifacts` as one recovery set.
- Preserve the volume across application image replacement and container recreation.
- Monitor free space, inode use, read/write failures, and backup completion.
- Restore the database and artifacts to a mutually consistent recovery point.
- Do not mount the volume into Nginx or enable `PUBLIC_OUTPUTS_ENABLED` in production.

## Scaling boundary

The named Docker volume is valid for a single Docker host. Before API or worker replicas run
on different hosts, supply either a shared POSIX-compatible filesystem mounted at the exact
same container path or implement a separately reviewed object-storage adapter. An object or
cloud provider is deliberately not selected or implemented in Phase 0.8.

## Runtime proof

The disposable `celery-smoke` stack mounts one test volume into separate API and worker
containers. The worker writes a FIRRIS artifact and the API reads it through the protected
result-product endpoint. Successful retrieval therefore verifies both the artifact manifest
and the shared-mount topology.

For coordinated recovery and production capacity evidence, follow
`docs/BACKUP_RESTORE_RUNBOOK.md` and `docs/FIRRIS_CAPACITY_TEST_PROCEDURE.md`.

