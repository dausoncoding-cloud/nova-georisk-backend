# NOVA API Gap Matrix — Phase 0.75 / Phase 1 Readiness

## Scope and interpretation

This assessment is based only on the current contents of:

- `app/api`
- `app/bff`
- `app/schemas`
- `app/services`
- `app/models`
- `openapi`
- `tests`

No endpoint is assumed to exist unless it is registered in source or present in the checked-in OpenAPI documents. The browser-facing route for an internal API operation is the same `/api/v1/...` path, but the request must traverse the BFF proxy. FastAPI's `X-Internal-Secret` contract is server-to-server only and is not a browser authentication mechanism.

Layer terminology used below:

- **BFF** — the browser-facing FastAPI application in `app/bff/main.py`.
- **BFF → API** — the browser calls the BFF's `/api/v1/{path}` proxy; the BFF validates the opaque session and CSRF token, strips browser identity headers, and calls the internal API with trusted identity headers.
- **API** — the internal FastAPI application. Its OpenAPI uses `X-Internal-Secret`; it is not intended to be called directly by React.

Status meanings:

- **Implemented** — an evidenced browser-consumable contract exists for the stated capability.
- **Partial** — useful implementation exists, but an important Phase 1 workflow or contract remains incomplete.
- **Missing** — no frontend-consumable endpoint or contract was found. Models or service code alone do not count as an implemented frontend capability.

## Authentication

| Capability | Existing endpoint(s) | HTTP method | Layer | Authentication requirement | Authorization requirement | Current status | Evidence | Next action |
|---|---|---|---|---|---|---|---|---|
| OIDC configuration discovery | `/auth/config` | GET | BFF | None | None | Implemented | `app/bff/main.py`; `app/schemas/auth.py`; `openapi/nova-browser-api.json` | Generate the Phase 1 client type and use it to decide whether login can be offered. |
| Login | `/auth/login` | GET | BFF | None; starts managed OIDC Authorization Code flow with PKCE | Membership is resolved only after the callback | Implemented | `app/bff/main.py`; `app/bff/oidc.py`; `tests/unit/test_bff_oidc.py` | Consume as a full-page browser navigation, not an AJAX token flow. |
| OIDC callback | `/auth/callback` | GET | BFF | Valid state cookie, one-time Redis state, authorization code, nonce, and validated ID token | Requires a valid NOVA database membership, valid invitation under the optional policy, or the explicitly enabled non-production first-user bootstrap | Implemented | `app/bff/main.py`; `app/bff/oidc.py`; `app/bff/membership.py`; `tests/unit/test_bff_oidc.py`; `tests/integration/test_oidc_membership.py` | Keep provider credentials and tokens server-side; add the callback state/error cases to the frontend login UX. |
| Browser session | `/auth/session` | GET | BFF | Optional opaque HttpOnly session cookie; unauthenticated callers receive `authenticated=false` | Returns the organization and role captured at login | Implemented | `app/bff/main.py`; `app/bff/session.py`; `app/schemas/auth.py`; `tests/unit/test_phase0_security.py` | Use this as the application bootstrap query. Do not store a provider token in React. |
| Logout | `/auth/logout` | POST | BFF | Valid opaque session cookie and CSRF header | Current session only | Implemented | `app/bff/main.py`; `app/bff/session.py`; `tests/unit/test_phase0_security.py` | Wire the UI to send `X-CSRF-Token`; document that this revokes the NOVA session, not necessarily the upstream provider SSO session. |
| CSRF protection | Token is returned by `/auth/session`; enforced on `/auth/logout` and unsafe `/api/v1/*` proxy methods | GET for token; POST/PUT/PATCH/DELETE protected | BFF | Valid session for protected mutations | Constant-time match against the server-side session token | Implemented | `app/bff/main.py`; `app/bff/session.py`; `tests/unit/test_phase0_security.py` | Centralize CSRF-header injection in the generated/client transport layer. |
| Browser-safe API proxy | `/api/v1/{path}` | GET, POST, PUT, PATCH, DELETE | BFF → API | Valid opaque session; CSRF for unsafe methods | Internal API revalidates active membership, project ownership, role, and/or engine entitlement by operation | Implemented | `app/bff/main.py`; `tests/unit/test_phase0_security.py`; `tests/integration/test_phase0_authorization.py` | Keep all React API traffic on the same origin and through this proxy. |

## Organization and identity

| Capability | Existing endpoint(s) | HTTP method | Layer | Authentication requirement | Authorization requirement | Current status | Evidence | Next action |
|---|---|---|---|---|---|---|---|---|
| Current user profile | `/auth/session` | GET | BFF | Valid session for populated response | None beyond the session | Implemented | `app/schemas/auth.py`; `app/bff/main.py`; `tests/unit/test_phase0_security.py` | Use the returned ID, email, and display name for the Phase 1 shell. |
| Current organization context | `/auth/session`; `/api/v1/organizations/current`; `/auth/login?organization_id=...` | GET | BFF and BFF → API | Valid session for current context; OIDC login for selection | The selected organization must have an active membership | Partial | `app/bff/main.py`; `app/bff/membership.py`; `app/api/v1/endpoints/organizations.py`; `app/schemas/identity.py` | The authenticated context is now complete. A pre-session multi-organization selection flow remains to be defined. |
| List memberships / organizations for current user | `/api/v1/organizations/current` | GET | BFF → API | Valid session | Active current membership; returns only memberships belonging to the current user | Implemented | `app/api/v1/endpoints/organizations.py`; `app/schemas/identity.py`; `tests/integration/test_phase08_commercial_contracts.py` | Use the memberships array for organization-aware UI after login. |
| Active membership revalidation | All protected `/api/v1/*` operations | Operation-dependent | API behind BFF | Valid BFF session plus trusted internal context | The API checks the database membership on protected operations | Implemented | `app/api/v1/endpoints/projects.py`; `app/api/v1/endpoints/engines.py`; `tests/integration/test_platform_engines.py` | Preserve per-request database revalidation. Consider whether `/auth/session` should also reflect revocation immediately rather than only API calls rejecting it. |
| Current role exposure | `/auth/session`; `/api/v1/organizations/current` | GET | BFF and BFF → API | Valid session | Returns and revalidates the selected membership role | Implemented | `app/schemas/auth.py`; `app/schemas/identity.py`; `app/api/v1/endpoints/organizations.py`; `tests/integration/test_phase08_commercial_contracts.py` | Use for conditional UI; role administration remains a separate missing contract. |
| Role/membership administration | None | — | — | — | — | Missing | Roles and memberships exist in `app/models/identity.py`; no create/update/delete API is registered | Add explicitly authorized membership and role administration contracts; do not infer permissions solely in React. |
| Organization administration | None | — | — | — | — | Missing | `app/models/identity.py`; absence from `app/api/v1/router.py` and OpenAPI paths | Define organization detail/update and membership-management scope if these are Phase 1 screens. |

## Projects

| Capability | Existing endpoint(s) | HTTP method | Layer | Authentication requirement | Authorization requirement | Current status | Evidence | Next action |
|---|---|---|---|---|---|---|---|---|
| List projects | `/api/v1/projects` | GET | BFF → API | Valid browser session | Active membership; results are restricted to the selected organization and actively entitled engines | Implemented | `app/api/v1/endpoints/projects.py`; `tests/integration/test_projects_api.py`; `tests/integration/test_platform_engines.py` | Generate the client operation. Add pagination/search only if Phase 1 data-volume requirements demand it. |
| Create project | `/api/v1/projects` | POST | BFF → API | Valid session and CSRF | OWNER, ADMIN, or ANALYST; organization membership; requested engine entitlement | Implemented | `app/api/v1/endpoints/projects.py`; `tests/integration/test_projects_api.py`; `tests/integration/test_phase0_authorization.py` | Build the creation form from `ProjectCreateRequest`; show entitlement failures explicitly. |
| Retrieve project | `/api/v1/projects/{project_id}` | GET | BFF → API | Valid session | Active membership, project organization access, and engine entitlement | Implemented | `app/api/v1/endpoints/projects.py`; `tests/integration/test_projects_api.py` | Use as the project workspace bootstrap query. |
| Update project | `/api/v1/projects/{project_id}` | PATCH | BFF → API | Valid session and CSRF | OWNER, ADMIN, or ANALYST; project access and engine entitlement | Implemented | `app/api/v1/endpoints/projects.py`; `tests/integration/test_phase08_commercial_contracts.py`; both OpenAPI documents | Build edit controls for name, description, and CRS only; engine reassignment is intentionally unsupported. |
| Delete/archive project | `/api/v1/projects/{project_id}` deletes empty projects only | DELETE | BFF → API | Valid session and CSRF | OWNER or ADMIN; project access and engine entitlement | Partial | `app/api/v1/endpoints/projects.py`; `tests/integration/test_phase08_commercial_contracts.py` | Empty-project deletion is safe. Projects with AOIs, jobs, or results return 409; archival semantics remain undefined. |
| Project access control | Enforced by project list/detail and all project-scoped AOI/task/result operations | Operation-dependent | API behind BFF | Valid session | Organization match, active membership, role where needed, and engine entitlement | Implemented | `app/api/v1/endpoints/projects.py`; `app/api/v1/endpoints/aoi.py`; `app/api/v1/endpoints/tasks.py`; `tests/integration/test_phase0_authorization.py` | Preserve server-side checks; React authorization is presentation-only. |

## Areas of Interest (AOI)

| Capability | Existing endpoint(s) | HTTP method | Layer | Authentication requirement | Authorization requirement | Current status | Evidence | Next action |
|---|---|---|---|---|---|---|---|---|
| Create drawn/GeoJSON AOI | `/api/v1/aoi` | POST | BFF → API | Valid session and CSRF | OWNER, ADMIN, or ANALYST; project access and engine entitlement | Implemented | `app/api/v1/endpoints/aoi.py`; `app/schemas/common.py`; `tests/integration/test_aoi_api.py` | Send Polygon/MultiPolygon GeoJSON in EPSG:4326 and render returned computed statistics. |
| Upload AOI | `/api/v1/aoi/upload` | POST multipart | BFF → API | Valid session and CSRF | OWNER, ADMIN, or ANALYST; project access and engine entitlement | Partial | `app/api/v1/endpoints/aoi.py`; `tests/integration/test_aoi_upload_api.py` | Current upload supports one zipped shapefile up to 20 MB. KML and GPKG are enumerated source types but have no upload implementation; either constrain Phase 1 UI or implement and test those formats later. |
| Retrieve AOI detail | `/api/v1/aoi/{aoi_id}` | GET | BFF → API | Valid session | Active membership, project access, and engine entitlement | Implemented | `app/api/v1/endpoints/aoi.py`; `app/api/v1/serializers.py`; `tests/integration/test_aoi_api.py` | Use returned GeoJSON, CRS, source type, area, perimeter, and timestamp directly. |
| List project AOIs | `/api/v1/projects/{project_id}/aois?limit=&offset=` | GET | BFF → API | Valid session | Active membership, project access, and engine entitlement | Implemented | `app/api/v1/endpoints/projects.py`; `app/schemas/common.py`; `tests/integration/test_aoi_api.py` | Use the provided pagination envelope. |
| AOI validation | Validation occurs during `POST /api/v1/aoi` and `POST /api/v1/aoi/upload` | POST | BFF → API | Valid session and CSRF | Same as AOI creation | Partial | `app/api/v1/endpoints/aoi.py`; `app/schemas/common.py`; `tests/integration/test_aoi_api.py`; `tests/integration/test_aoi_upload_api.py` | Creation-time validation exists, but no non-persisting preflight endpoint exists. Either accept validation-on-submit for Phase 1 or define a preflight contract. |
| Update/delete AOI | `/api/v1/aoi/{aoi_id}` | PATCH, DELETE | BFF → API | Valid session and CSRF | Update: OWNER, ADMIN, or ANALYST. Delete: OWNER or ADMIN; AOIs with task/result history return 409 | Implemented | `app/api/v1/endpoints/aoi.py`; `tests/integration/test_firris_execution.py` | Geometry is immutable after creation; use PATCH for the name and DELETE only for history-free AOIs. |

## FIRRIS analysis and results

| Capability | Existing endpoint(s) | HTTP method | Layer | Authentication requirement | Authorization requirement | Current status | Evidence | Next action |
|---|---|---|---|---|---|---|---|---|
| Legacy synchronous FIRRIS calculations | `/api/v1/firas/hazard`, `/exposure`, `/capacity-subindex`, `/vulnerability`, `/insecurity`, `/resilience`, `/risk` | POST | BFF → API | Valid session and CSRF | Active membership and effective FIRRIS entitlement | Implemented | `app/api/v1/endpoints/firas.py`; `app/schemas/firas.py`; `app/services/firas`; `tests/integration/test_firas_api.py` | Compatibility-only calculator routes; new frontend workflows should use persistent analyses. |
| Discover engine execution contract | `/api/v1/analyses/engines/{engine_key}` | GET | BFF → API | Valid session | Active membership and effective engine entitlement | Implemented | `app/api/v1/endpoints/analyses.py`; `app/platform/engines`; `app/schemas/analyses.py` | Use the shared contract to discover operations/products and delivered GIS capabilities. |
| Submit persistent FIRRIS job | `/api/v1/analyses` | POST | BFF → API | Valid session and CSRF | OWNER, ADMIN, or ANALYST; project/AOI access and engine entitlement | Implemented | `app/api/v1/endpoints/analyses.py`; `app/platform/engines/firris.py`; `app/workers/celery_tasks.py`; `tests/integration/test_firris_execution.py` | Submit the selected FIRRIS products through this engine-neutral operation; poll the returned canonical Task. |
| Job list/filtering | `/api/v1/tasks?project_id=&aoi_id=&status=&task_type=&engine_key=&limit=&offset=` | GET | BFF → API | Valid session | Active membership; organization isolation; active engine entitlement filtering | Implemented | `app/api/v1/endpoints/tasks.py`; `app/schemas/common.py`; `tests/integration/test_tasks_api.py`; `tests/integration/test_ingestion_api.py` | Use the typed page response for the jobs screen. |
| Job status/detail | `/api/v1/tasks/{task_id}` | GET | BFF → API | Valid session | Active membership, project access, and engine entitlement | Implemented | `app/api/v1/endpoints/tasks.py`; `app/api/v1/serializers.py`; `tests/integration/test_tasks_api.py` | Poll while queued/running; expose only `error_summary`, never raw worker exceptions. |
| General result list/detail | `/api/v1/results`; `/api/v1/results/{result_id}`; task responses also include `result_reference` | GET | BFF → API | Valid session | Active membership, organization isolation, project access for detail, and effective engine entitlement | Implemented | `app/api/v1/endpoints/results.py`; `app/schemas/results.py`; `app/api/v1/serializers.py`; `tests/integration/test_phase08_commercial_contracts.py` | Use the paginated contract for history and the typed detail for summary/provenance/products. Storage paths are never returned. |
| Screening-atlas manifest | `/api/v1/maps/atlas/{project_id}/{aoi_id}` | GET | BFF → API | Valid session | Active membership, project access, FIRAS project, and entitlement | Implemented | `app/api/v1/endpoints/maps.py`; `app/schemas/atlas.py`; `tests/integration/test_atlas_manifest_api.py` | Use the newest persisted Result-backed manifest and honor its `legacy` and nullable `crs` fields. |
| Protected result download | `/api/v1/results/{result_id}/products/{product_key}` | GET | BFF → API | Valid session | Active membership, project access, and result engine entitlement | Implemented | `app/api/v1/endpoints/results.py`; `tests/integration/test_phase0_authorization.py`; `tests/unit/test_gee_atlas_orchestrator.py` | Fetch through the same-origin BFF; do not construct or expose filesystem paths. |
| Legacy atlas product download | `/api/v1/maps/atlas/{project_id}/{aoi_id}/products/{product_key}` | GET | BFF → API | Valid session | Active membership, project access, FIRAS entitlement | Partial | `app/api/v1/endpoints/maps.py`; `tests/integration/test_atlas_manifest_api.py` | Keep only for backward compatibility. Prefer Result-based product URLs for new outputs. |

## Google Earth Engine workflow

| Capability | Existing endpoint(s) | HTTP method | Layer | Authentication requirement | Authorization requirement | Current status | Evidence | Next action |
|---|---|---|---|---|---|---|---|---|
| Trigger GEE processing | `/api/v1/ingestion/screening-atlas` | POST | BFF → API | Valid session and CSRF | OWNER, ADMIN, or ANALYST; project/AOI access; FIRAS entitlement | Partial | `app/api/v1/endpoints/ingestion.py`; `app/schemas/ingestion.py`; `app/services/gee/atlas_orchestrator.py`; `tests/integration/test_ingestion_api.py` | Screening-atlas processing is implemented. Other GEE pipeline services have no registered trigger routes and must not be presented as frontend capabilities. |
| Worker/task status | `/api/v1/tasks/{task_id}` and `/api/v1/tasks` | GET | BFF → API | Valid session | Organization/project/entitlement checks | Implemented | `app/api/v1/endpoints/tasks.py`; `app/models/task.py`; `tests/integration/test_tasks_api.py` | Poll the task contract; cancellation and retry are available as explicit POST transitions. Streaming progress is not implemented. |
| GEE atlas outputs | Atlas manifest and protected product routes above | GET | BFF → API | Valid session | Project access and FIRAS entitlement | Partial | `app/services/gee/export.py`; `app/services/gee/atlas_orchestrator.py`; `app/schemas/atlas.py`; `tests/unit/test_gee_atlas_orchestrator.py`; `tests/integration/test_atlas_manifest_api.py` | Current products are PNG renderings. New manifests provide bounds, EPSG:4326, dimensions, units/nodata/legend where available, periods, version, and provenance; legacy PNGs have `crs=null` and must remain preview-only. Do not treat them as GIS-native rasters. |
| Worker cancellation/retry | `/api/v1/tasks/{task_id}/cancel`; `/api/v1/tasks/{task_id}/retry` | POST | BFF → API | Valid session and CSRF | OWNER, ADMIN, or ANALYST; project access and engine entitlement | Implemented | `app/api/v1/endpoints/tasks.py`; `app/workers/celery_tasks.py`; `tests/integration/test_firris_execution.py` | Cancel is valid for queued/running tasks. Retry is valid for failed/canceled tasks and creates a new task for auditability. |

## Platform, engines, entitlements, and billing readiness

| Capability | Existing endpoint(s) | HTTP method | Layer | Authentication requirement | Authorization requirement | Current status | Evidence | Next action |
|---|---|---|---|---|---|---|---|---|
| Discover available engines | `/api/v1/engines` | GET | BFF → API | Valid browser session; service-only context is rejected | Active membership; only enabled, effectively entitled engines are returned | Implemented | `app/api/v1/endpoints/engines.py`; `app/schemas/platform.py`; `tests/integration/test_platform_engines.py` | Use this response to build engine navigation. Do not hard-code access from provider claims. |
| Inspect organization entitlements | `/api/v1/organizations/{organization_id}/engine-entitlements` | GET | BFF → API | Valid session | Same organization and OWNER or ADMIN; internal service context also supported | Implemented | `app/api/v1/endpoints/engines.py`; `app/schemas/platform.py`; `tests/integration/test_platform_engines.py` | Suitable for a read-only admin view. Keep provider/billing identifiers hidden. |
| Grant/update/revoke entitlements | None | — | — | — | — | Missing | Entitlement model exists in `app/models/platform.py`; endpoint module is read-only | Define an administrative contract only when an authorized entitlement-management workflow is approved. |
| Billing plan/subscription readiness | None; persistence models only | — | — | — | — | Partial | `BillingPlan`, `BillingPlanEngine`, and `OrganizationSubscription` in `app/models/platform.py`; no registered API or browser schema | The database is billing-ready, but Phase 1 cannot list plans, show subscription state, or initiate billing. Keep billing UI out of scope until contracts are defined. |
| Usage limits/consumption | None | — | — | — | — | Missing | `usage_limits` fields exist in `app/models/platform.py`; no usage/consumption endpoint exists | Do not show quotas or consumption until authoritative accounting and read contracts exist. |

## Administration, invitations, and provisioning

| Capability | Existing endpoint(s) | HTTP method | Layer | Authentication requirement | Authorization requirement | Current status | Evidence | Next action |
|---|---|---|---|---|---|---|---|---|
| Accept invitation during login | `/auth/login?invitation=...` followed by `/auth/callback` | GET | BFF | Valid OIDC login with verified matching email | Valid, unexpired, unused invitation; optional-invite policy; row-locked single-use consumption | Partial | `app/bff/main.py`; `app/bff/membership.py`; `app/models/identity.py`; `tests/integration/test_oidc_membership.py` | Consumption is implemented, but strict staging policy does not use it and no frontend/admin invitation issuance workflow exists. |
| Create/list/revoke invitations | None | — | — | — | — | Missing | Invitation persistence exists in `app/models/identity.py`; no route is present in `app/api`, `app/bff`, or OpenAPI | Define owner/admin-only invitation lifecycle contracts if administration is part of Phase 1. Never expose stored token hashes. |
| Provision users and memberships | None | — | — | — | — | Missing | `app/bff/membership.py` enforces strict pre-provisioning; `app/models/identity.py` stores users/memberships; no provisioning API exists | Retain the administrator-controlled database model. Add a separately authorized provisioning surface or keep this as an operational process outside Phase 1. |
| Disable/reactivate users | None | — | — | — | — | Missing | `User.is_active` exists in `app/models/identity.py`; protected API rejection is tested in `tests/integration/test_platform_engines.py` | Add an audited administrative contract before exposing this action. Existing API requests already reject disabled users. |

## Cross-cutting frontend contract readiness

| Capability | Existing endpoint(s) | HTTP method | Layer | Authentication requirement | Authorization requirement | Current status | Evidence | Next action |
|---|---|---|---|---|---|---|---|---|
| Browser OpenAPI as React client source | `/auth/*`, `/health`, and proxied `/api/v1/*` operations are composed into the browser document | — | BFF/OpenAPI | Cookie authentication is implicit; no internal security scheme is exposed | Operation-specific authorization remains server-side | Implemented | `app/bff/openapi.py`; `scripts/export_bff_openapi.py`; `openapi/nova-browser-api.json`; `tests/unit/test_openapi_contract.py` | Generate the React TypeScript client only from `openapi/nova-browser-api.json`. Never generate browser code from the internal document. |
| Stable public error envelope | All BFF/API routes through shared exception handling | Operation-dependent | BFF and API | Operation-dependent | Operation-dependent | Implemented | Error declarations in both OpenAPI documents; `app/schemas/errors.py`; endpoint/error tests under `tests/unit/test_phase0_security.py` and `tests/integration` | Generate and handle the common error envelope in the React client; map codes rather than raw exception text. |
| Raw worker-error suppression | `/api/v1/tasks` and `/api/v1/tasks/{task_id}` | GET | BFF → API | Valid session | Task visibility rules | Implemented | `app/api/v1/serializers.py`; `app/models/task.py`; `tests/integration/test_tasks_api.py` | Display only `error_summary`; never surface the persisted raw `error_message`. |
| Collection pagination | Project AOIs and tasks are paginated; projects and engines are unpaginated | GET | BFF → API | Valid session | Resource-specific access controls | Partial | `app/api/v1/endpoints/projects.py`; `app/api/v1/endpoints/tasks.py`; `app/api/v1/endpoints/engines.py` | Confirm expected Phase 1 collection sizes. Add pagination contracts before relying on unbounded project/engine responses at scale. |

## Readiness summary

### Ready for Phase 1 consumption

- Provider-neutral OIDC login/callback and Redis-backed opaque browser sessions.
- Browser session bootstrap, current user, selected organization, and current role.
- BFF CSRF enforcement and secure internal API proxying.
- Project list/create/detail/update and guarded deletion with organization and entitlement isolation.
- GeoJSON AOI creation, zipped-shapefile upload, AOI detail/list, rename, and guarded deletion.
- Generic FIRRIS submission, screening-atlas submission, typed task polling, cancellation, and retry.
- Versioned atlas manifests and authorized product delivery.
- Read-only engine discovery and organization entitlement inspection.
- Stable public error responses and safe task error summaries.

### Top blockers before treating the complete React Phase 1 scope as ready

1. **Pre-session multi-organization selection is incomplete.** Authenticated users can now read all their memberships, but a user with multiple memberships cannot discover them before the callback asks for an organization selection.
2. **Administrative provisioning has no browser API.** Strict membership remains secure, but invitations, membership creation, role changes, and user activation/deactivation lack authorized API contracts.
3. **Archive semantics remain intentionally constrained.** Empty projects and history-free AOIs can be deleted, but preserving analytical history takes precedence over cascading deletion; project archival is not defined.
4. **GIS-native delivery is implemented for 2D satellite-workflow products.** FIRRIS results can deliver protected GeoTIFF, COG, preview, metadata, and Flood Extent GeoJSON artifacts. Direct one-dimensional product inputs remain metadata-only. Existing screening-atlas outputs remain PNG previews.
5. **Billing is persistence-ready only.** There is no plan, subscription, checkout, usage, or entitlement-mutation API. Billing UI is not Phase 1-ready.

### Recommended Phase 1 boundary

The browser-safe OpenAPI source is now resolved. An initial Phase 1 slice can cover login, session bootstrap, authenticated organization context, engine discovery, project lifecycle, AOI lifecycle, generic FIRRIS submission, screening-atlas submission, task polling/cancellation/retry, result history/detail, atlas display, and protected downloads.

Organization administration, membership provisioning, project archival, GIS-native raster/vector visualization, and billing should remain out of the first React slice unless their missing contracts are implemented and tested first.
