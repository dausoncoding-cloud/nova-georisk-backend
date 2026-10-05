# NOVA FIRRIS production operations checklist

## Ownership and service objectives

- [ ] Name an on-call owner for Nginx/TLS, BFF/Auth0, API/PostGIS, Redis/Celery, GEE, and artifact storage.
- [ ] Approve availability, API latency, task-start latency, task-completion, RPO, and RTO objectives.
- [ ] Maintain provider escalation contacts for Auth0, Google Earth Engine/cloud, DNS, and the hosting platform.
- [ ] Keep a release inventory containing image digests, Alembic revision, configuration version, and rollback owner.

The repository supplies container health checks and application logs. It does not install a metrics, alerting, log-retention, tracing, or paging platform; production approval requires those external controls.

## Health monitoring

Poll from both inside and outside the deployment:

| Area | Signal | Alert guidance |
|---|---|---|
| Public gateway | HTTPS `/healthz` and `/healthz/frontend` | Page after two consecutive failures; validate certificate separately |
| BFF | `/healthz/bff` through Nginx and `/health` internally | Alert on failure or elevated 401/403/5xx changes from baseline |
| API | Container health and `/health` internally | Page when unhealthy; do not expose internal health with trusted headers |
| Worker | Container health plus Celery `inspect ping` | Page when zero production workers answer twice |
| PostGIS | `pg_isready`, connections, locks, storage, backup age | Warn before 80% resource use; critical before exhaustion |
| Redis | `PING`, memory, evictions, connected clients, persistence/HA state | Page on unavailability or evictions; record accepted durability policy |
| GEE | Initialization/export failures, quota and authentication errors | Alert on repeated failures or quota exhaustion |
| Artifact store | Free bytes, free inodes, write failures, backup age | Warn at 20% free; critical at 10% free unless stricter host policy applies |
| TLS/DNS | Certificate days remaining, renewal result, DNS resolution | Alert at 30/14/7 days and immediately on failed renewal |

Run the built-in status checks during incident triage:

```bash
docker compose ps
docker compose exec -T nginx nginx -t
docker compose exec -T worker celery -A app.core.celery_app.celery_app inspect ping --timeout 5
docker compose exec -T redis redis-cli ping
docker compose exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

## Logs

- [ ] Ship stdout/stderr from Nginx, BFF, API, worker, Redis, and PostGIS to restricted centralized storage.
- [ ] Retain `X-Request-Id`, task ID, Result ID, service, severity, timestamp, and release/image identity.
- [ ] Correlate browser/API failures by request ID and asynchronous failures by task ID.
- [ ] Restrict raw worker exceptions and `Task.error_message`; normal users see only `error_summary`.
- [ ] Redact cookies, authorization codes, OIDC tokens, client secrets, internal API secret, GEE credentials, database URLs/passwords, and invitation tokens.
- [ ] Alert on unhandled exceptions, repeated OIDC/JWKS failures, database/Redis connection failures, artifact write failures, and task hard/soft limits.
- [ ] Set retention and access-review periods consistent with the organization’s privacy/security policy.
- [ ] Test that log export failure does not fill the host disk silently.

Routine review command (local triage only):

```bash
docker compose logs --since=30m --tail=500 nginx bff api worker
```

Do not paste unredacted production logs into public tickets or chat systems.

## Queue and task monitoring

Inspect Celery state:

```bash
docker compose exec -T worker celery -A app.core.celery_app.celery_app inspect active --timeout 10
docker compose exec -T worker celery -A app.core.celery_app.celery_app inspect reserved --timeout 10
docker compose exec -T worker celery -A app.core.celery_app.celery_app inspect scheduled --timeout 10
docker compose exec -T worker celery -A app.core.celery_app.celery_app inspect stats --timeout 10
```

Monitor database lifecycle counts and age, not only broker depth:

- queued count and oldest queued age;
- running count and oldest running age;
- completion/failure/cancellation rate;
- queue-to-start and start-to-completion duration;
- tasks approaching the 10,800-second default soft limit;
- tasks with missing `celery_task_id` or inconsistent terminal timestamps;
- duplicate Result versions or completed tasks without Results.

Alert before the oldest task reaches its approved service objective or 80% of the configured soft time limit, whichever is earlier. Never change a database Task to `completed` manually.

## Worker operations

- [ ] Keep concurrency at the capacity-tested value; the default is one heavy task per worker.
- [ ] Confirm container memory exceeds `CELERY_WORKER_MAX_MEMORY_PER_CHILD_KB` plus parent/runtime overhead.
- [ ] Confirm `CELERY_WORKER_MAX_TASKS_PER_CHILD=1` recycles the child after heavy geospatial work.
- [ ] Track worker/container restart counts and distinguish configured child recycling from container crashes.
- [ ] Before maintenance, block submissions and drain active/reserved work; do not terminate a worker writing an artifact unless incident response requires it.
- [ ] After an unexpected worker exit, reconcile database `queued`/`running` Tasks, broker state, partial files, and Result rows before retrying.
- [ ] Retrying creates a new auditable Task; do not reuse or mutate a failed Task into success.
- [ ] Scale only within the single-host shared-volume boundary and capacity-test each new concurrency value.

## Storage and database operations

- [ ] Monitor PostGIS and artifact volume independently for bytes, inodes, I/O latency, and errors.
- [ ] Run coordinated backups and periodic isolated restores using `BACKUP_RESTORE_RUNBOOK.md`.
- [ ] Preserve the `nova_artifacts` and PostGIS volumes during deploy/rollback; never run `docker compose down -v` in production.
- [ ] Verify Result paths remain relative and resolve under `/app/outputs`.
- [ ] Investigate orphan files conservatively. No automated orphan deletion is currently approved.
- [ ] Use matched recovery points for database and artifact recovery.
- [ ] Monitor database connection count, long transactions, lock waits, vacuum/analyze health, table/index growth, and backup duration.

## Security operations

- [ ] Review Auth0, database, host, and gateway administrator access at an approved interval.
- [ ] Rotate secrets on schedule and after suspected disclosure; validate BFF/API together when rotating the internal secret.
- [ ] Review NOVA memberships and FIRRIS entitlements independently of Auth0 roles/groups.
- [ ] Test a disabled user, revoked membership, expired entitlement, logout, and session expiry after each security-sensitive release.
- [ ] Review 401/403/404/429 patterns without weakening intentional resource concealment.
- [ ] Verify `/outputs/*` remains unavailable and internal service ports remain unexposed.
- [ ] Patch base images and dependencies in a controlled maintenance release, then rerun all RC gates.

## Daily checks

- [ ] All containers healthy; worker ping succeeds.
- [ ] No abnormal growth in queued/running/failed tasks.
- [ ] PostGIS, Redis, artifact, and host capacity above alert thresholds.
- [ ] Latest backup completed and copied off-host.
- [ ] No certificate, Auth0, GEE, or secret-rotation alert.

## Weekly checks

- [ ] Review task latency/failure trends and top resource-consuming jobs.
- [ ] Review container restarts, OOM events, disk/inode growth, database locks, and Redis evictions.
- [ ] Sample one protected Result and verify its artifact checksum/download authorization.
- [ ] Review high-severity security and access events.

## Release/change window

- [ ] Capture matched backup and verify checksums.
- [ ] Record current image digests and Alembic revision.
- [ ] Validate Compose and production environment.
- [ ] Apply migrations before application traffic.
- [ ] Pass internal health, external HTTPS/Auth0, tenant-isolation, FIRRIS workflow, COG range, and export checks.
- [ ] Observe error/latency/queue/storage signals for the agreed stabilization window.
- [ ] Keep rollback authority available until the window closes.

## Incident priorities

1. Protect tenant isolation and secrets; block public traffic if authorization boundaries are uncertain.
2. Stop new submissions if queue, worker, PostGIS, Redis, or artifact persistence is inconsistent.
3. Preserve logs, database, artifacts, and failed containers for diagnosis.
4. Recover PostGIS and artifacts as one set when restoration is required.
5. Reopen traffic only after authentication, authorization, persistence, and one protected FIRRIS workflow pass.
