# NOVA PostGIS and artifact backup/restore runbook

## Recovery contract

PostGIS and `nova_artifacts` form one recovery set:

- PostGIS contains projects, AOIs, tasks, Results, relative artifact manifests, identities, memberships, and entitlements.
- `nova_artifacts` contains the files referenced by Result manifests.

A database-only restore can leave missing files; an artifact-only restore can leave unreferenced files. Back up and restore both under one recovery-set identifier and to the same quiet point.

Redis is not authoritative for users, memberships, tasks, or Results. Losing Redis invalidates browser sessions/OIDC transactions and may lose queued messages in the base non-persistent configuration. After Redis loss, reconcile queued/running database Tasks before accepting new submissions.

## Define recovery objectives before deployment

Record and approve:

- Recovery point objective (RPO).
- Recovery time objective (RTO).
- Backup frequency and retention tiers.
- Backup storage location, encryption method, key owner, and immutability policy.
- Restore-test frequency and responsible operator.
- Maximum acceptable artifact/data loss for an in-flight task.

No default RPO/RTO is implied by Docker volumes.

## Backup procedure

Run from the production project directory. Examples assume a Linux host and an operator-selected backup directory outside the repository and Docker volumes.

### 1. Prepare a quiet point

1. Announce the maintenance window and block new browser mutations at the external gateway/load balancer.
2. Confirm Celery is reachable:

   ```bash
   docker compose exec -T worker celery -A app.core.celery_app.celery_app inspect ping --timeout 5
   ```

3. Allow active tasks to finish. Inspect active, reserved, and scheduled work until all are empty:

   ```bash
   docker compose exec -T worker celery -A app.core.celery_app.celery_app inspect active --timeout 10
   docker compose exec -T worker celery -A app.core.celery_app.celery_app inspect reserved --timeout 10
   docker compose exec -T worker celery -A app.core.celery_app.celery_app inspect scheduled --timeout 10
   ```

4. Stop BFF/API to prevent new database writes, then stop the worker after it is idle:

   ```bash
   docker compose stop bff api
   docker compose stop worker
   ```

5. Confirm no `running` Tasks remain. Any stranded row must be investigated; do not silently mark it completed.

### 2. Resolve exact sources

Load only the non-secret database names needed by the commands:

```bash
POSTGRES_USER_VALUE="$(docker compose exec -T postgres printenv POSTGRES_USER | tr -d '\r')"
POSTGRES_DB_VALUE="$(docker compose exec -T postgres printenv POSTGRES_DB | tr -d '\r')"
ARTIFACT_VOLUME="$(docker inspect "$(docker compose ps -q api)" --format '{{range .Mounts}}{{if eq .Destination "/app/outputs"}}{{.Name}}{{end}}{{end}}')"
```

If API is already stopped and `docker compose ps -q api` returns no container ID, resolve the existing stopped container with `docker compose ps -aq api`. Stop if `ARTIFACT_VOLUME` is empty or is not the expected NOVA artifact volume.

Create a recovery-set directory with a UTC identifier:

```bash
RECOVERY_SET="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT="/srv/nova-backups/$RECOVERY_SET"
mkdir -p "$BACKUP_ROOT"
chmod 700 "$BACKUP_ROOT"
```

### 3. Back up PostGIS

Create a custom-format logical dump:

```bash
docker compose exec -T postgres pg_dump \
  -U "$POSTGRES_USER_VALUE" \
  -d "$POSTGRES_DB_VALUE" \
  --format=custom \
  --no-owner \
  --no-privileges \
  > "$BACKUP_ROOT/postgis.dump"
```

Validate the dump catalogue before continuing:

```bash
pg_restore --list "$BACKUP_ROOT/postgis.dump" > "$BACKUP_ROOT/postgis.catalog.txt"
test -s "$BACKUP_ROOT/postgis.catalog.txt"
```

If `pg_restore` is unavailable on the host, run the catalogue check in a pinned PostgreSQL 16 client container with the backup directory mounted read-only.

Record authoritative row counts for later comparison:

```bash
docker compose exec -T postgres psql \
  -U "$POSTGRES_USER_VALUE" \
  -d "$POSTGRES_DB_VALUE" \
  -Atc "SELECT 'organizations', count(*) FROM organizations UNION ALL SELECT 'users', count(*) FROM users UNION ALL SELECT 'organization_memberships', count(*) FROM organization_memberships UNION ALL SELECT 'projects', count(*) FROM projects UNION ALL SELECT 'aois', count(*) FROM aois UNION ALL SELECT 'tasks', count(*) FROM tasks UNION ALL SELECT 'results', count(*) FROM results ORDER BY 1" \
  > "$BACKUP_ROOT/database-counts.txt"
```

### 4. Back up artifacts

Archive the exact resolved volume read-only:

```bash
docker run --rm \
  -v "$ARTIFACT_VOLUME:/source:ro" \
  -v "$BACKUP_ROOT:/backup" \
  alpine:3.20 \
  tar -C /source -czf /backup/nova_artifacts.tar.gz .
```

Record metadata without secrets:

```bash
docker compose run --rm --no-deps api alembic current > "$BACKUP_ROOT/alembic-revision.txt"
docker image inspect "$(docker compose images -q api)" --format '{{json .RepoDigests}}' > "$BACKUP_ROOT/api-image-digests.json"
sha256sum "$BACKUP_ROOT/postgis.dump" "$BACKUP_ROOT/nova_artifacts.tar.gz" > "$BACKUP_ROOT/SHA256SUMS"
```

If local image naming differs, use the immutable image reference recorded for the release.

### 5. Secure and release the quiet point

1. Encrypt/copy the complete recovery-set directory to approved backup storage.
2. Verify remote object size and checksum.
3. Restart services and remove maintenance mode:

   ```bash
   docker compose up -d api worker bff
   ```

4. Confirm API, worker, BFF, PostGIS, Redis, and artifact-storage health.
5. Record start/end time, recovery-set ID, checksums, operator, and failures.

## Restore rehearsal procedure

Restore tests must run on an isolated host/project with no production ingress. Never rehearse by overwriting production volumes.

### 1. Verify backup material

```bash
cd /srv/nova-backups/<recovery-set>
sha256sum --check SHA256SUMS
pg_restore --list postgis.dump > /dev/null
```

Stop if either verification fails.

### 2. Create isolated targets

Use a distinct Compose project name so restore containers and volumes cannot collide with production:

```bash
export COMPOSE_PROJECT_NAME="nova-restore-<recovery-set>"
docker compose up -d postgres redis
```

Resolve the isolated artifact volume only after Compose creates it. Never reuse the production volume name.

### 3. Restore PostGIS

Resolve the isolated database variables and replace only the empty rehearsal database:

```bash
RESTORE_DB_USER="$(docker compose exec -T postgres printenv POSTGRES_USER | tr -d '\r')"
RESTORE_DB_NAME="$(docker compose exec -T postgres printenv POSTGRES_DB | tr -d '\r')"
docker compose exec -T postgres dropdb -U "$RESTORE_DB_USER" --if-exists "$RESTORE_DB_NAME"
docker compose exec -T postgres createdb -U "$RESTORE_DB_USER" "$RESTORE_DB_NAME"
docker compose exec -T postgres pg_restore \
  -U "$RESTORE_DB_USER" \
  -d "$RESTORE_DB_NAME" \
  --no-owner \
  --no-privileges \
  < postgis.dump
```

The `dropdb` step is destructive. It is permitted only after confirming the distinct rehearsal `COMPOSE_PROJECT_NAME`, resolved container identity, and empty target database.

### 4. Restore artifacts

Resolve the isolated named volume from the restore API container, confirm it is not the production name, then extract into the empty volume:

```bash
docker compose create api
RESTORE_ARTIFACT_VOLUME="$(docker inspect "$(docker compose ps -aq api)" --format '{{range .Mounts}}{{if eq .Destination "/app/outputs"}}{{.Name}}{{end}}{{end}}')"
docker run --rm -v "$RESTORE_ARTIFACT_VOLUME:/restore:ro" alpine:3.20 \
  sh -c 'test -z "$(find /restore -mindepth 1 -print -quit)"'
docker run --rm \
  -v "$RESTORE_ARTIFACT_VOLUME:/restore" \
  -v "$(pwd):/backup:ro" \
  alpine:3.20 \
  tar -C /restore -xzf /backup/nova_artifacts.tar.gz
```

The explicit emptiness check must succeed. Stop if the resolved name is empty, matches production, or the target volume is not empty.

### 5. Start and verify recovery

```bash
docker compose run --rm api alembic current
docker compose up -d api worker bff
```

Required recovery evidence:

- [ ] All containers become healthy without applying an unexpected migration.
- [ ] Counts for organizations, users, memberships, projects, AOIs, tasks, and Results match the backup record.
- [ ] No Task is incorrectly left `running`; each in-flight record has an explicit operator disposition.
- [ ] A representative Result manifest loads and exposes no filesystem path.
- [ ] Every sampled manifest entry resolves beneath `/app/outputs` and exists.
- [ ] Downloaded sample artifacts match their stored SHA-256 metadata.
- [ ] A COG supports authorized byte-range retrieval and renders in the browser.
- [ ] PDF, Excel/CSV, GIS package, and provenance downloads open successfully.
- [ ] Cross-organization result and artifact requests still return 404.
- [ ] A new post-restore FIRRIS task completes and persists a new Result without overwriting an existing version.

Record achieved RPO/RTO and compare them with the approved objectives. A backup policy is not accepted until at least one isolated restore passes.

## Production recovery

Use the same verified procedure only during an approved incident/change window. Block ingress, stop mutating services, preserve the failed volumes for forensics, restore into newly identified targets where possible, and require two-person verification of every destructive target. After cutover, rotate secrets if compromise is possible and retain the pre-recovery state until incident closure.
