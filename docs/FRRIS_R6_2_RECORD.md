# FRRIS release r6.2: pre-release record (prepared, NOT deployed)

**Prepared:** 2026-11-20.
**Status:** tests passed; waiting for the owner's "deploy". The production server is suspended (unpaid hosting bill) and has not been touched.

**Scope:** two small frontend fixes, the user guide (v1.1) and three docs branches merged into `main`. There is no backend code change, no API change and no database change.

## 1. Changes

| Area | Change | Backlog |
|---|---|---|
| Frontend, result page | The **Modelled hazard** and **Exposure** tabs used CSS classes that were never defined (`fr-stack`, `fr-notice`, `fr-badge`), and their cards had no `fr-section`. As a result: text touched the card edges, the cards had no spacing between them, the "not available" notices and the commission-error caveat were unstyled, and the badges showed as plain text. They now use the shared classes (`fr-tab-stack`, `fr-card fr-section`, `fr-pill fr-pill--neutral`, `fr-box fr-box--warning`) like the other tabs. The Modelled hazard tab had the same defect | §4.7 item 26 (done) |
| Frontend, tests | The flaky tests are fixed at the root. Async lookups (`findBy*`, `waitFor`) now wait up to 5 s (`src/test/setup.ts`, one setting), and a test may take 15 s (`vitest.config.ts`). Two tests in `AnalysisSubmitPage.test.tsx` now wait for asynchronous state (the navigation after submit; the project, area and selection loading) instead of checking it once. No assertion was weakened | §4.7 item 24 (done) |
| User guide | `FRRIS_User_Guide.pdf` v1.1: version pill "Guide v1.1 · FRRIS r6.2"; the Modelled hazard and Exposure screenshots recaptured with the fix (local stack, placeholder user). 38 pages, 32 figures | — |
| Docs merged into `main` (merge commits, no force-push) | `docs/frris-user-guide` (the guide, Quick start, DEETEKI contact); `docs/client-change-requests-2026-11` (the Depth & Exposure and multi-ROC plans, the depth/risk feasibility study, the S2 partial-coverage proposal C1/D7 with the ward-level exposure design C2, and remediation plan §1.9). The remediation plan merged automatically and was checked: both sides' content is kept; backlog items 8–26 appear once each; no conflict markers. `docs/firris-scientific-output-gap-audit` (the 7 Nov audit) | — |
| Branches | Deleted the superseded `feat/frris-depth-exposure` (both repos; its content has been on `main` since r6). Pushed `docs/depth-risk-data-feasibility` as a record branch (not merged). `feat/frris-science-3-hsba` stays unmerged as the record of a tested, not-adopted design | — |

## 2. Commits

| | Backend | Frontend |
|---|---|---|
| Base (production r6.1) | `9f3b187` (tag `firris-science-2-r6.1`) | `1d0e588` (tag `firris-science-2-r6.1`) |
| r6.2 candidate | `main` `34f8389` and later (docs and guide only on top of r6.1 code) | `874ff5b` on `fix/frris-r6.2`, fast-forwarded into `main` |

Because the backend code is unchanged, an r6.2 deploy only needs a new **frontend** image. Running the full Phase A gates on both images is still recommended (same procedure as r6.1).

## 3. Tests

| Suite | Result |
|---|---|
| Backend compile check (`python -m compileall app scripts`) | clean |
| Backend unit (on `199844b`, the docs merges and the guide) | **1,256 passed**, 0 failed (31 min 59 s) |
| Backend integration (Docker, PostGIS) | **191 passed** |
| Packaging regression | PACKAGING REGRESSION PASS |
| Frontend `typecheck`, `api:check`, `build` | pass (0 type errors; the generated API matches `openapi/`) |
| Frontend tests, **10 consecutive default (4-worker) runs** | **258/258 in each run**: the acceptance criterion of item 24. Before the fix, 3 of 10 runs failed, across 6 different tests |

**Lint:** neither repo has a linter configured: no ruff, flake8 or mypy in the backend, and no ESLint in the frontend. The strict TypeScript check is the frontend's static check. Adding a linter is proposed as backlog item 27.

## 4. Deploy notes (for when the owner says "deploy", after "server is booted")

- **Procedure:** the r6.1 procedure: Phase A (builds, gates, OpenAPI hash, candidate compose, one-off worker under 120 s), then Phase B in tmux with backup, health waits, logs saved before any rollback, and automatic rollback.
- **OpenAPI:** expected unchanged, `58ffc5593d7622dfa106db05a5ece8d10c5cfa270931eac56b8b0d9abc13e160`.
- **Owner browser test after deploy:** open a result with the modelled hazard and exposure; check that the cards on both tabs have padding and spacing, and that the caveat is an amber box.
