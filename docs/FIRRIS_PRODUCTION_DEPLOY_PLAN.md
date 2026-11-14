# FIRRIS production deploy plan — Bundle 1 + Bundle 2 + report polish

**Prepared:** 2026-11-14 (Phase A preflight, read-only). **Status:** plan only; nothing merged, pushed to `main` or deployed.
**Targets:** `app.novageorisk.com` / `api.novageorisk.com`, host `deploy@172.236.139.113` (ED25519 host key verified earlier through LISH).

| Repo | `origin/main` | Deploy commit (`fix/firris-report-polish`) | Commits landing | Merge |
|---|---|---|---|---|
| backend | `2eafee7` | `1ece5d1fedc097da699bd9e1953774065ea61f8e` | 54 | fast-forward, 0 conflicts (dry run) |
| frontend | `d082746` | `4c441161345198536767d77d946162e54e67f41c` | 10 | fast-forward, 0 conflicts (dry run) |

Browser OpenAPI SHA-256 (both repos and the new image at runtime): `cd0e4e8ac43117ee02b600c010e4d6e7ea71e37ba401a5d0eb96019a2905a1ca`.

## 1. Production as found (read-only inspection, 2026-11-14 01:07 UTC)

- **Compose project:** `firris-release-2f1b2dc`. Active file: `/home/deploy/nova-releases/firris-2f1b2dc/compose.active.json`, identical (SHA-256) to `management-41a7fa2-20261024/compose.candidate.json`.
- **Services:**
  - `firris-2f1b2dc-api`, `-worker` and `-bff` all run backend image `sha256:25c5e8187827…` (`nova-georisk-backend:management-41a7fa2-20261024`, revision `41a7fa2`, user `nova`).
  - `firris-2f1b2dc-gateway` runs frontend image `sha256:0cc61c0fbf26…` (`nova-georisk-frontend:management-b43974e-20261024`, revision `b43974e`).
  - All four are healthy.
- **Shared, not replaced:** `nova-georisk-engine-postgres-1`, `-redis-1` and `-nginx-1`.
- **Database:**
  - `nova_georisk_firris_2f1b2dc`, Alembic `f1a2b3c4d5e6`, size 21 MB.
  - Tasks: 26 (5 COMPLETED, 20 FAILED, 1 QUEUED). The QUEUED task is `86408bc6…`, created 2026-09-22, and is not in the broker.
  - Results: 3.
- **Broker:** `LLEN celery` = 0.
- **Artifacts volume:** `firris_release_2f1b2dc_artifacts`, 20.8 MB.
- **Host:**
  - 1 vCPU, 1.9 GiB RAM.
  - `/` 49 GB, 19 GB free.
  - Docker build cache 11.96 GB, of which 3.66 GB is reclaimable.
  - No sudo for `deploy`.
- **Inspection side effect:** while measuring the artifacts volume, a read-only `docker run --rm alpine:3` pulled the image `alpine:3` (`f59abe656b69`). No container remains and no data was touched. Remove it only on the owner's instruction: `docker image rm alpine:3`.

## 2. Rollback targets

| Component | Image | Revision |
|---|---|---|
| api / worker / bff | `nova-georisk-backend:management-41a7fa2-20261024` = `sha256:25c5e8187827edef8334aa33f6f0c01c81046edaba5a0e8c7eee01f9d028b33d` | `41a7fa2` |
| gateway | `nova-georisk-frontend:management-b43974e-20261024` = `sha256:0cc61c0fbf262afe9c04c5d46dc46284a40071086b5143ff9ff0a02d6ac7cd4d` | `b43974e` |
| database | Alembic `f1a2b3c4d5e6` (unchanged by this release) | — |

Step 4.4 also tags both images `:rollback-before-report-polish`, so they survive any image cleanup.

## 3. Migrations, environment and runtime

- **Migrations: none.**
  - The Alembic head of `1ece5d1` is `f1a2b3c4d5e6`, equal to production.
  - `git diff origin/main..1ece5d1 -- app/db/migrations alembic.ini` is empty.
  - There is no schema change, so no downgrade target is needed.
- **New environment variables: none.** The release adds no new settings or runtime environment variables. The only additions are image-level `ENV MPLBACKEND=Agg` and `MPLCONFIGDIR=/home/nova/.config/matplotlib` in the Dockerfile. The candidate compose keeps the 47 existing variable names and their values unchanged (check in 4.5).
- **MPLCONFIGDIR:** verified in the new image `sha256:783a4f14…`, built locally from `1ece5d1`. Running as `nova`, the backend is `Agg`, the directory is writable, a figure saves, and DejaVu Sans registers.
- **Workers:** api, worker and bff are replaced together in one `docker compose up` call, from one image. The worker is never left on the old code.
- **Data compatibility:** the three existing results are served through the legacy paths (no overview gates beyond the recorded quality; legacy download grouping). New report, figure and map artifacts appear only for new runs.

## 4. Deploy procedure (Phase B — requires explicit go-ahead)

Set these once, in the operator shell on the workstation:

```bash
REL=report-polish-1ece5d1-$(date -u +%Y%m%d)
BE_SHA=1ece5d1fedc097da699bd9e1953774065ea61f8e
FE_SHA=4c441161345198536767d77d946162e54e67f41c
HOST=deploy@172.236.139.113
SSH="ssh -o BatchMode=yes -o HostKeyAlgorithms=ssh-ed25519 $HOST"
```

### 4.1 Merge (workstation)

```bash
cd ~/projects/nova-georisk-backend && git fetch origin && git checkout main && git pull --ff-only \
  && git merge --ff-only origin/fix/firris-report-polish && test "$(git rev-parse HEAD)" = "$BE_SHA" && git push origin main
cd ~/projects/nova-georisk-frontend && git fetch origin && git checkout main && git pull --ff-only \
  && git merge --ff-only origin/fix/firris-report-polish && test "$(git rev-parse HEAD)" = "$FE_SHA" && git push origin main
```

The merges are fast-forward only, with no merge commit and no force push.

### 4.2 Ship source and build images (no downtime)

```bash
cd ~/projects/nova-georisk-backend  && git archive --format=tar "$BE_SHA" > /tmp/backend-$REL.tar
cd ~/projects/nova-georisk-frontend && git archive --format=tar "$FE_SHA" > /tmp/frontend-$REL.tar
$SSH "install -d -m 700 /home/deploy/nova-releases/$REL/{backup,rollback,backend-source,frontend-source}"
scp -o HostKeyAlgorithms=ssh-ed25519 /tmp/backend-$REL.tar  $HOST:/home/deploy/nova-releases/$REL/backend.tar
scp -o HostKeyAlgorithms=ssh-ed25519 /tmp/frontend-$REL.tar $HOST:/home/deploy/nova-releases/$REL/frontend.tar
$SSH "cd /home/deploy/nova-releases/$REL && tar -xf backend.tar -C backend-source && tar -xf frontend.tar -C frontend-source \
  && docker build --label org.opencontainers.image.revision=$BE_SHA -t nova-georisk-backend:$REL backend-source > backend-build.log 2>&1 \
  && docker build --label org.opencontainers.image.revision=$FE_SHA -t nova-georisk-frontend:$REL frontend-source > frontend-build.log 2>&1 \
  && docker image inspect --format '{{.Id}} {{index .Config.Labels \"org.opencontainers.image.revision\"}}' nova-georisk-backend:$REL nova-georisk-frontend:$REL"
```

- The builds use the repositories' own Dockerfiles: explicit `COPY` lists and `.dockerignore`, with no broad copy.
- On 1 vCPU, expect 15–40 minutes, before any downtime. If disk is tight, `docker builder prune --filter until=168h` frees about 3.7 GB of reclaimable cache; ask before running it.

### 4.3 Image gates (no downtime)

```bash
$SSH "cd /home/deploy/nova-releases/$REL && python3 backend-source/scripts/check_image_packaging.py nova-georisk-backend:$REL > backend-packaging.json \
  && python3 backend-source/scripts/check_image_packaging.py nova-georisk-frontend:$REL > frontend-packaging.json; echo rc=\$?"
$SSH "docker run --rm --user nova --entrypoint python nova-georisk-backend:$REL -c \
  'import os,matplotlib,matplotlib.pyplot as p;p.figure().savefig(\"/tmp/t.png\");from app.services.reporting.fonts import register_fonts;register_fonts();print(matplotlib.get_backend(),os.access(os.environ[\"MPLCONFIGDIR\"],os.W_OK))'"
$SSH "docker run --rm --user nova --entrypoint python -e APP_ENV=test nova-georisk-backend:$REL -c \
  'import json,hashlib;from app.bff.main import app;print(hashlib.sha256((json.dumps(app.openapi(),indent=2,sort_keys=True)+\"\\n\").encode()).hexdigest())'"
```

The gates pass only if all of these hold:
- Both packaging scans return rc 0 with no findings. The backend scan uses the reviewed exceptions in `backend-source/scripts/docker_packaging_exceptions.json`.
- The MPLCONFIGDIR check prints `Agg True`.
- The OpenAPI SHA equals `cd0e4e8a…a1ca`.

### 4.4 Candidate compose and rollback set (no downtime)

```bash
$SSH "cd /home/deploy/nova-releases/$REL && cp -p ../firris-2f1b2dc/compose.active.json rollback/compose.previous.json \
  && docker tag sha256:25c5e8187827edef8334aa33f6f0c01c81046edaba5a0e8c7eee01f9d028b33d nova-georisk-backend:rollback-before-report-polish \
  && docker tag sha256:0cc61c0fbf262afe9c04c5d46dc46284a40071086b5143ff9ff0a02d6ac7cd4d nova-georisk-frontend:rollback-before-report-polish \
  && python3 - <<'PY'
import json, subprocess
from pathlib import Path
R = Path('/home/deploy/nova-releases/$REL')
c = json.loads((R / 'rollback/compose.previous.json').read_text())
image = lambda tag: subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag], text=True).strip()
be, fe = image('nova-georisk-backend:$REL'), image('nova-georisk-frontend:$REL')
for name in ('firris-2f1b2dc-api', 'firris-2f1b2dc-worker', 'firris-2f1b2dc-bff'):
    c['services'][name]['image'] = be
c['services']['firris-2f1b2dc-gateway']['image'] = fe
out = R / 'compose.candidate.json'; out.write_text(json.dumps(c, indent=2)); out.chmod(0o600)
print('candidate written; images', be[:19], fe[:19])
PY
docker compose -f compose.candidate.json config --quiet && docker compose -f rollback/compose.previous.json config --quiet && echo configs-ok"
```

### 4.5 Environment parity check (no downtime; prints no values)

```bash
$SSH "cd /home/deploy/nova-releases/$REL && python3 -c \"
import json
a=json.load(open('rollback/compose.previous.json'));b=json.load(open('compose.candidate.json'))
for s in a['services']:
    ka=a['services'][s].get('environment');kb=b['services'][s].get('environment')
    assert ka==kb,s
    del a['services'][s]['image'];del b['services'][s]['image']
assert a==b
print('environment and all non-image settings identical')\""
```

### 4.6 Quiesce and back up (downtime starts)

```bash
$SSH "docker exec nova-georisk-engine-redis-1 redis-cli LLEN celery"          # must print 0
$SSH "docker exec firris-release-2f1b2dc-firris-2f1b2dc-worker-1 celery -A app.core.celery_app.celery_app inspect active --timeout 5"  # no active tasks
$SSH "docker stop --time 30 firris-release-2f1b2dc-firris-2f1b2dc-bff-1 firris-release-2f1b2dc-firris-2f1b2dc-api-1 firris-release-2f1b2dc-firris-2f1b2dc-worker-1"
$SSH "cd /home/deploy/nova-releases/$REL/backup && STAMP=\$(date -u +%Y%m%dT%H%MZ) \
  && docker exec nova-georisk-engine-postgres-1 sh -c 'pg_dump -U \"\$POSTGRES_USER\" -d nova_georisk_firris_2f1b2dc -Fc' > production-\$STAMP.dump \
  && chmod 600 production-\$STAMP.dump && ls -l production-\$STAMP.dump && sha256sum production-\$STAMP.dump > production-\$STAMP.dump.sha256 \
  && docker exec -i nova-georisk-engine-postgres-1 pg_restore --list < production-\$STAMP.dump | grep -c 'TABLE DATA' \
  && docker run --rm --user root --entrypoint tar -v firris_release_2f1b2dc_artifacts:/a:ro nova-georisk-backend:rollback-before-report-polish -czf - -C /a . > artifacts-\$STAMP.tar.gz \
  && chmod 600 artifacts-\$STAMP.tar.gz && ls -l artifacts-\$STAMP.tar.gz"
```

The backup passes only if all of these hold:
- The dump is non-empty. Last time it was 200–215 kB for a 21 MB database (custom format, compressed).
- `pg_restore --list` lists TABLE DATA entries.
- The artifacts archive is about 7 MB or more (20.8 MB uncompressed).

Stop if any check fails, and restart the old services with `docker start <the three names>`.

### 4.7 Migration step (no-op, verified)

```bash
$SSH "cd /home/deploy/nova-releases/$REL && docker compose -f compose.candidate.json run --rm --no-deps firris-2f1b2dc-api alembic current \
  && docker compose -f compose.candidate.json run --rm --no-deps firris-2f1b2dc-api alembic heads"
```

Both must print `f1a2b3c4d5e6`. Do **not** run `alembic upgrade`. If they differ, stop and restart the old services.

### 4.8 Activate (backend + worker + BFF together, then frontend)

```bash
$SSH "cd /home/deploy/nova-releases/$REL && docker compose -f compose.candidate.json up -d --no-deps --no-build --pull never \
  firris-2f1b2dc-api firris-2f1b2dc-worker firris-2f1b2dc-bff"
$SSH 'for c in api worker bff; do n=firris-release-2f1b2dc-firris-2f1b2dc-$c-1; for i in $(seq 90); do s=$(docker inspect --format "{{.State.Health.Status}}" $n); [ "$s" = healthy ] && break; sleep 2; done; echo "$n $s"; done'
$SSH "cd /home/deploy/nova-releases/$REL && docker compose -f compose.candidate.json up -d --no-deps --no-build --pull never firris-2f1b2dc-gateway \
  && for n in firris-release-2f1b2dc-firris-2f1b2dc-gateway-1 nova-georisk-engine-nginx-1; do docker exec \$n nginx -t && docker exec \$n nginx -s reload; done \
  && cp -p compose.candidate.json ../firris-2f1b2dc/compose.active.json"
```

Downtime ends when api, bff and worker report healthy.

## 5. Post-deploy checks

1. **Images:** `docker inspect --format '{{.Name}} {{.Image}} {{.State.Health.Status}}'` on the four containers. The three backend containers show the `nova-georisk-backend:$REL` ID, the gateway shows the `nova-georisk-frontend:$REL` ID, and all are healthy.
2. **Revision labels:** the backend image label is `1ece5d1f…` and the frontend label is `4c441161…`.
3. **Environment parity at runtime:** compare the sorted env name+value sets of old (rollback set) and new containers inside a Python check that prints only `identical`/`differs`, as `cutover.py` did.
4. **Health:**
   - `curl -fsS https://api.novageorisk.com/health` (or the BFF route used before) returns 200.
   - `curl -fsSI https://app.novageorisk.com/` returns 200 and the new bundle hash appears in `index.html`.
5. **Worker:** `celery … inspect ping` and `inspect registered` show `nova.tasks.run_engine_analysis`. `docker exec <worker> python -c` checks that `MPLCONFIGDIR` is writable as `nova`.
6. **OpenAPI at runtime:** run the SHA command from 4.3 with `docker exec <bff>`. It must equal `cd0e4e8a…`.
7. **Database unchanged:** `alembic current` is `f1a2b3c4d5e6`. Read-only counts are 26 tasks and 3 results (no change by the deploy).
8. **Browser (owner):**
   - Sign in and open an existing result: the overview renders and the download groups show (legacy grouping for old results).
   - Open Data Catalog: it shows the "Flood-candidate mapping (model-classified)" wording.
   - No console errors.
9. **Optional functional check (owner decision; uses GEE quota):** submit the Rufiji 2024 AOI and dates. The result should carry the scientific report (PDF/DOCX), the framed maps, the figures and the curated download groups.

## 6. Rollback

The database schema is unchanged, so rollback needs **no Alembic downgrade and no restore**. Use the saved compose and the preserved images:

```bash
$SSH "cd /home/deploy/nova-releases/$REL && docker compose -f rollback/compose.previous.json up -d --no-deps --no-build --pull never \
  firris-2f1b2dc-api firris-2f1b2dc-worker firris-2f1b2dc-bff firris-2f1b2dc-gateway \
  && for n in firris-release-2f1b2dc-firris-2f1b2dc-gateway-1 nova-georisk-engine-nginx-1; do docker exec \$n nginx -t && docker exec \$n nginx -s reload; done \
  && cp -p rollback/compose.previous.json ../firris-2f1b2dc/compose.active.json"
```

- Afterwards, verify images `25c5e818…` (backend ×3) and `0cc61c0f…` (gateway) and health, as in step 5.1.
- **Frontend only:** run the same command with only `firris-2f1b2dc-gateway`, and write the gateway entry of `compose.previous.json` into `compose.active.json`.
- **Data restore (only if data were damaged, which this release does not do):** stop api, bff and worker, then:

  ```bash
  docker exec -i nova-georisk-engine-postgres-1 sh -c 'pg_restore -U "$POSTGRES_USER" -d nova_georisk_firris_2f1b2dc --clean --if-exists --single-transaction' < backup/production-<STAMP>.dump
  ```

  Then restore the artifacts volume from `artifacts-<STAMP>.tar.gz`, and start the rollback compose. This needs explicit owner approval at the time.
- **Results created by the new release:** the old code serves them through its legacy paths; the additional artifacts are ignored.

## 7. Expected downtime

| Phase | Effect | Estimate |
|---|---|---|
| Build, image gates, candidate (4.2–4.5) | none | 20–45 min |
| Quiesce → backup → migration check → activate → healthy (4.6–4.8) | API, BFF and worker unavailable; the SPA loads but sign-in and API calls fail | **2–5 min** (backup of 21 MB takes seconds; health deadline 3 min) |
| Gateway swap + nginx reload | SPA served by new gateway | seconds |
| Rollback, if needed | same as activation | 2–3 min |

## 8. Test evidence on the deploy commits (2026-11-14)

| Check | Result |
|---|---|
| Backend unit (`1ece5d1`) | 1008 passed |
| Backend integration (`NOVA_TEST_DB_PORT=56432`) | 174 passed |
| `scripts/verify_docker_packaging.py` | NEGATIVE IMAGE PASS, CONTEXT PASS, PACKAGING REGRESSION PASS; 0 findings; 44 reviewed dependency matches |
| Frontend `api:check`, `typecheck`, `build` | pass |
| Frontend `test` | 29 files / 124 tests pass (two clean runs). A first run under Docker build load had 3 worker-start timeouts, then 1 timing failure; neither reproduced |
| Frontend `lint` | **not available**: `package.json` has no `lint` script and no ESLint/Biome configuration |
