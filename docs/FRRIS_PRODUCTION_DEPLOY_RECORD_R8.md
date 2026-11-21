# FRRIS production deploy record: release r8 (r7 + platform subscriptions, enforcement OFF)

**Date:** 2026-11-21 (UTC).
**Host:** `deploy@172.236.139.113` (`app.novageorisk.com`, `api.novageorisk.com`).
**Release:** r8 = r7 + platform subscriptions: credits, payments, statuses, sessions, the NOVA ARI console and My subscription (`docs/PLATFORM_SUBSCRIPTIONS_RELEASE_RECORD.md`). It is deployed with **`BILLING_ENFORCEMENT_ENABLED=false`**, so nothing changes for customers: no 402s, seat checks or charges.
**Result:** deployed at the first attempt, no rollback. API/BFF downtime **58.8 s**. Phase A and Phase B ran on the owner's "go"; Phase B ran in `tmux` session `r8-cutover`.

**The first r8 attempt (2026-11-21, about 03:00 UTC)** stopped when the owner's laptop lost power. Production was unchanged, still r7 and healthy. The only trace was an empty release folder (`r8-2090ce2-20261121`), which was removed. Phase A had found 7 frontend type errors on `8b8238c`; they were fixed and merged as `5209096` (release record §5.2), and r8 restarted from there.

Internal identifiers keep the old spelling (`FIRRIS_*` files, engine key `firris`, `firris-science-2`).

## 1. Code, tags and images

| | Backend | Frontend |
|---|---|---|
| Deployed commit | **`b94ebb6152e6764a3dab5d38d02131b20a3f8ca8`** (subscriptions merge `2090ce2` + the release-record note) | **`5209096e9562ab1d19de33fa0ff85a77b37d6bfb`** (subscriptions merge `8b8238c` + typecheck fix `ea632e5`) |
| Tag | `firris-science-2-r8` | `firris-science-2-r8` |
| Deployed image | `nova-georisk-backend:r8-b94ebb6-20261121` = `sha256:4e4b50e65c19babad668772bbc8466b78302ba3887419e218811bfb623e43c31` | `nova-georisk-frontend:r8-5209096-20261121` = `sha256:4ac9dd6b191093ce6fdfb8e748ad7ac356fa1d9f9675738ed903f0246a1f7438` |
| Rollback image (`:rollback-before-r8`) | `sha256:fe937dc1c6b0…` (r7, `3560fca`) | `sha256:cdc94293e419…` (r7, `e825f27`) |

**API schema:** the browser OpenAPI SHA-256 is **`77ecb8aa19fad6299647ae5793eb2be6010d9792ace65ba81f7e016ca78302c8`**, the same in both repositories, in the image and at runtime.

**Dependencies:** `requirements.lock`, `package-lock.json`, both Dockerfiles and `.dockerignore` are unchanged since r7. `pip freeze --all` in the image is identical to r7 (111 packages).

**Database:** Alembic **`f1a2b3c4d5e6` → `c5e7a9b1d3f6`**, 7 migrations (`a9c3e5f70b12`, `c4e6a8b0d2f1`, `e8b0c2d4f6a3`, `f2c4e6a8b0d5`, `a7b9c1d3e5f2`, `b3d5f7a9c1e4`, `c5e7a9b1d3f6`). Tables went from 20 to 32.

## 2. Phase A

| Check | Result |
|---|---|
| Backend suites (clean worktree at `b94ebb6`) | compile clean; **unit 1,311 passed**; **integration 260 passed**; PACKAGING REGRESSION PASS; OpenAPI `77ecb8aa…` |
| Frontend gate (tree of `5209096` = `ea632e5`) | `npm run typecheck`, `api:check` and `build` pass; **288/288** tests in 47 files |
| Source transfer | tar SHA-256 equal on workstation and server (backend `5e933e5594ec…`, frontend `4c4f5a86dd28…`) |
| **Server builds** (sequential, production up) | **Backend:** 8 s, minimum MemAvailable 778 MB. **Frontend:** 64 s, minimum MemAvailable **410 MB**; swap in use 132 → **266 MB** at the peak. App 200 throughout |
| Image gates | **Backend packaging:** 0 findings (44 reviewed). **Frontend:** the same 2 reviewed public-CA files as every release. **Matplotlib:** `Agg` |
| Content | **Backend:** 7 migrations, head `c5e7a9b1d3f6`, `billing_enforcement_enabled` defaults to False, the four CLIs present, no `/app/docs`. **Frontend:** console (`nova-ari`) present; Trends present; 12 woff2; 0 Google Fonts; 0 references to `api.novageorisk.com`. The signed-out notice text is served by the API (`NOTICE_REPLACED`), not built into the bundle |
| **Migration rehearsal** (scratch database `nova_r8_rehearsal`; production running; the live database only dumped) | See below |
| One-off worker (candidate image, throwaway queue, new secret) | Healthy in **18.6 s** (limit 120 s); healthcheck ×5 1.9–5.1 s, all rc 0; 0 tasks; no `VersionMismatch`; no container left |

**Migration rehearsal steps:**
1. **Dump:** the live database was dumped (1,678,258 B, 26 tables with data).
2. **Restore:** the dump was restored into the scratch database with the live owner, encoding and collation. Row counts equal: 41 tasks, 16 results, 23 AOIs, 7 projects, 1 organization, 3 users, 1 dataset.
3. **Migrate:** `alembic upgrade head` in **4.3 s**. Minimum MemAvailable 1,079 MB; maximum swap 430 MB.
4. **Catalogue:** **14 plans** (2 Internal) and **12 prices**; 9 new tables. `billing.cli seed`, run twice, added nothing (idempotent).
5. **Rollback restore path:** drop, recreate and `pg_restore` in **3.4 s**. The result was back at `f1a2b3c4d5e6`, counts identical, 0 r8 tables left.
6. **Cleanup:** the scratch database was dropped. The live database was unchanged (`f1a2b3c4d5e6`).

### Candidate compose (`make_candidate.py`, asserted)
- **Images:** the r8 images.
- **`INTERNAL_API_SECRET` rotated (security review M1):**
  - generated on the server (`secrets.token_urlsafe(48)`, 64 characters) and written only into the candidate compose file (mode 600);
  - the same value on api, bff and worker, and different from the previous one;
  - **never printed**: the script printed only the length, the equality checks and the "differs" check.
- **`BILLING_ENFORCEMENT_ENABLED=false`:** set explicitly on api, bff and worker.
- **Gateway:** mounts the r8 `gateway.conf` from the release folder (mode 600). It is the live file plus `proxy_set_header X-Nova-Session-Ref "";` next to each of the three `X-Nova-Role ""` lines (A13).
- **Everything else:** environment, mounts, limits and health checks are identical to r7 (asserted).

## 3. Backup, migration and cutover

The cutover used `cutover.py`: the r7 procedure plus the migration, with a database restore in every rollback branch (`dbtools.py`).

| Item | Value |
|---|---|
| Artifacts base (services running) | `backup/artifacts-20261121T0414Z-base.tar.gz`, 586,080,547 B, 103.8 s |
| Gates | Broker (db 3) empty, worker idle (04:16:09) |
| **Pre-migration DB dump** (quiesced) | `backup/production-20261121T0414Z-pre-migration.dump`, 1,678,258 B, 26 TABLE DATA entries, SHA-256 `10891efffa6e661b3963600f07906c1ee18a956c205f3176f7551afef5e613b4` |
| **Dump verified** before upgrading | Full restore into scratch `nova_r8_dumpcheck`: row counts and table count (20) equal the quiesced live database; 4.4 s; scratch dropped |
| Artifacts incremental (quiesced) | 8,257 B, 0.9 s |
| Alembic precheck | current `f1a2b3c4d5e6`, heads `c5e7a9b1d3f6` |
| **Migration** | `alembic upgrade head` in **2.7 s** (4.2 s including the checks). **Memory: minimum MemAvailable 1,382 MB, maximum swap 62 MB.** Row counts unchanged |
| Quiesce → new API/BFF/worker healthy | 04:16:09 → 04:17:08 UTC: **58.8 s** |
| Gateway swap + nginx reload | 7.6 s (done 04:17:15) |
| Restore check after the cutover | base + incremental restored in a throwaway container: **1,860 files, identical list and per-file SHA-256** to the live volume |

**Rollback (ready, not needed):**
- **Images and compose:** `rollback/compose.previous.json` with the `:rollback-before-r8` images.
- **Database:** restore the pre-migration dump with `dbtools.recreate_and_restore`, as rehearsed: drop, recreate with the recorded owner/encoding/collation, `pg_restore`, then check that alembic is `f1a2b3c4d5e6` and the counts are equal.
- **Edge:** the live files saved in `edge-conf.d/` (section 4).
- **Enforcement:** stays off, so the release record's own rollback (enforcement off) is the current state.

## 4. Edge nginx change (owner-approved)

- **Starting point:** the change was made to the **live** production files, not the repo copy. The live `app.conf` (from the October cutover) differs from `deploy/nginx/conf.d/app.conf`; see release record §5.2.
- **Evidence for locking the host:** before r8, the API host sent `/auth/*` and `/api/*` to the BFF. The read-only audit of 7–21 Nov found no real sign-ins or app traffic through it:
  - 0 `/auth/login` hits;
  - every successful `/api/*` call had an `app.novageorisk.com` referer;
  - the OIDC redirect is on the app host;
  - the session cookie is host-only.

**What changed:**
- **`app.conf`:** the API host serves **GET/HEAD `/health` only**, with identity headers blanked, `X-Nova-Session-Ref` included, and the request body dropped. Everything else is a JSON 404. The HTTP-80 server (ACME path), TLS, the security headers and CSP, and the two rate-limit zones that `frontend-app.conf` uses are kept.
- **Logging:** new `log_format main_host` (the `main` fields + `"$host"`) with a per-server `access_log` in both files. Each request is logged once, and `/auth` on the app host is still not logged.
- **`frontend-app.conf`:** only the two `access_log` lines.
- **Tests before deploy:** both files tested locally in nginx 1.27.5 (as in production) with stub upstreams. `nginx -t` passed, and the status codes and log lines were as expected.

**How it was applied (`edge_r8.py`):**
1. The live files were saved to `edge-conf.d/` (SHA-256 `3b08a5a4b192…`, `cb6604b0eeb0…`).
2. The new files were swapped in by atomic rename (`e9e049eea60a…`, `73f6a45907e6…`).
3. `nginx -t` passed; then a reload (no restart).
4. The checks below. Any failure would have restored the saved files and reloaded.

| Check (from the host) | Before | After |
|---|---|---|
| API host `GET /health` | 200 | **200** |
| API host `GET /api/v1/projects` | 401 (reached the BFF) | **404** |
| API host `GET /docs` | 302 | **404** |
| API host `POST /health` | 405 | **404** |
| API host `GET /auth/callback` | 400 (reached the BFF) | **404** |
| API host `GET /openapi.json` | 302 | **404** |
| App `/`, `/auth/session` | 200, 200 | 200, 200 |
| App `/auth/login` | 302 | 302 (Auth0) |
| App `/api/v1/results` without a session | 401 | 401 |

New log lines end with the host (8 in the first 30 s).

## 5. Phase A operator steps (on the live system, after activation)

| Step | Result |
|---|---|
| Seed the catalogue (`billing.cli seed`) | `{"plans": [], "engine_links": [], "prices": []}`: nothing to add, because the migrations seeded it. **14 plans (2 Internal), 12 prices** |
| Daily IP purge cron (required) | Tested: dry run and `--apply`, `{"ip_addresses": 0, "history_rows": 0}`. Installed: `17 0 * * *` (00:17 UTC = 03:17 EAT), `flock`, log `/home/deploy/nova-ops/logs/session-purge.log` |
| Usage-flush cron | Tested: `{"organization_days": 0}`. Installed: `*/15 * * * *`, `flock`, log `/home/deploy/nova-ops/logs/usage-flush.log` |
| Crontab | The existing app-certificate renewal line is kept; previous crontab saved to `/home/deploy/nova-ops/crontab.before-r8`. Server time zone: UTC |
| `X-Internal-Secret` rotated | See §2; api, bff and worker restarted with it by the cutover. Confirmed **only by health and status checks**, never printed: all three healthy; from inside the BFF, an API request with a wrong secret → 401, and with the BFF's own secret → accepted (200) |
| **NOVA ARI admin granted** | `platform_admin.cli grant --email <the owner's account> --operator "Dauson" --reason "initial platform admin"` → **internal user ID `3908bc44-da51-42e1-8f65-dd3d6bfaefb5`**. `list` shows 1 admin. Audit row: `platform_admin.grant`, actor `operator command: platform-admin grant (Dauson)`, reason "initial platform admin", 04:19:14 UTC |
| GeoIP | Skipped (owner decision); locations stay blank |
| Backfill | **Not run** (owner decision) |
| Enforcement | **OFF**: `BILLING_ENFORCEMENT_ENABLED=false` in api, bff and worker |
| Database after the steps | 0 ledger entries, 0 payments, 0 user sessions yet, 1 platform admin |

## 6. Post-deploy checks and smoke tests

| Check | Result |
|---|---|
| Services | api, bff and worker on `4e4b50e6…` (rev `b94ebb6`); gateway on `4ac9dd6b…` (rev `5209096`); all healthy, 0 restarts. `compose.active.json` = the r8 candidate |
| Gateway config | Mounted from `r8-b94ebb6-20261121/gateway.conf`; 3 `X-Nova-Session-Ref ""` lines in the running container |
| OpenAPI at runtime | `77ecb8aa…` |
| **App login page loads** | `/login` 200; `/auth/login` 302 → Auth0; `/auth/session` 200, including the new `signedOutNotice` field |
| **An existing result opens** | All **16** production results serialize with the live r8 code (`serialize_result`, read-only transaction, via stdin into the API container). Every stored file is present (`492c073c`: 140/140; `3fbedf95`: 129/129). The result page route `/frris/results/…` returns 200 |
| **API host** | `/health` **200**; `/api/v1/projects`, `/docs`, `POST /health` → **404** (section 4) |
| **`/nova-ari` for the owner** | The page route returns 200. From inside the BFF (its own secret, internal network): `GET /api/v1/platform-admin/access` as user `3908bc44…` → **200** |
| **403 for a non-admin** | The organisation has **no non-admin owner**: its only owner is the NOVA ARI admin, and the other two members are organisation admins. The test used admin `4262badd…` (no NOVA ARI role): `/access` → **403 `platform_admin_required`**, `/overview` → **403 `platform_admin_required`**, and the same user claiming `X-Nova-Role: owner` → **403**. The role header never grants the console |
| Without a session (app host) | 401 for: a result download, `/api/v1/platform-admin/access`, `/api/v1/billing/summary`, `/api/v1/account/sessions` |
| Worker | 1 node online; `run_engine_analysis` registered |
| Broker | `LLEN celery` (db 3) = 0 |
| Logs since 04:16:50 UTC | 0 errors / tracebacks / 5xx in api, bff, worker, gateway and the edge nginx |
| Memory after | 876 MB available, 59 MB swap in use |

**Owner browser confirmation still useful:**
1. Sign in.
2. Open a result.
3. Open `/nova-ari` (console tiles and customer table).
4. Open "My subscription" (no subscription rows until the backfill).

### Housekeeping
- **Redis:** the one-off worker left `_kombu.binding.diag_noop_r8_20261121t035443z` (db 3, a set). Its name was shown first, then only that key was deleted. No `diag_noop` key remains in databases 0–5. Nothing else in Redis was touched.
- **Read-only rule:** read-only checks and the internal smoke checks ran from outside the service containers (scripts on stdin, throwaway `--network none` containers). No file was copied into a service container (backlog item 25).
- **Scripts:** written locally and copied with `scp`, with the SHA-256 checked on both ends. A first rehearsal attempt failed at its first read-only query, because shell quoting had stripped quotes from a script written through `ssh`. Nothing had been dumped or written.
- **Old pre-FRRIS containers:** `nova-georisk-engine-api-1` and `-worker-1` are still stopped (backlog item 28).

## 7. Owner actions and follow-ups

- **Auth0 dashboard:** remove the allowed callback `https://api.novageorisk.com/auth/callback`; that host now returns 404 for it.
- **Phase B of the subscriptions release** (not started; release record §1 steps 2c–10):
  - the backfill dry run and apply;
  - `BILLING_OVERDUE_GRACE_FROM`;
  - the open client questions (Q9 to the client);
  - then enforcement.
- **Backlog 35 (urgent):** the **`api.novageorisk.com` certificate expires 24 Dec 2026** and has no renewal job (only the app certificate is renewed).
- **Backlog 36:** the old `INTERNAL_API_SECRET` remains in earlier release and rollback compose files (mode 600); clean them up once r8 is accepted.
- **Backlog 37:** an explicit default server for unknown hosts and the bare IP.
- **Next:** FRRIS v1.1 exposure by administrative level resumes on `feat/frris-admin-exposure`, rebased on this `main`.
