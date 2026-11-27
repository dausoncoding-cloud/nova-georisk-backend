# Production edge configuration (nova-georisk-engine-nginx-1)

These are the live edge files from `/home/deploy/nova-georisk-engine/deploy/nginx/conf.d/` on the production host,
added to the repository on 2026-11-27 so edge changes go through review and the deploy scripts, never by hand.

| File | Live since | Purpose |
|---|---|---|
| `app.conf` | r8 (2026-11-21) | `api.novageorisk.com`: GET/HEAD `/health` only; `main_host` log format; the two rate-limit zones |
| `frontend-app.conf` | r8 (2026-11-21); upload exception added on `feat/frris-wards-external-data` | `app.novageorisk.com`: `/auth/*` and `/api/*` to the BFF, everything else to the gateway |
| `default-server.conf` | backlog 37 (2026-11-21) | Unknown hosts and the bare IP: 444 on HTTP, TLS handshake refused |

`deploy/nginx/conf.d/app.conf` is the repository's own template and is **not** the live edge file.

Apply only through a release's edge step:
1. Copy the live files to the release folder as the rollback copy, checking their SHA-256 against the previous release.
2. Swap the new files in by atomic rename.
3. Run `nginx -t`, then reload (no restart).
4. Run the checks, and restore and reload if any check fails.
