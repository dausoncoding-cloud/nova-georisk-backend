# NOVA React Phase 1 Implementation Plan

## 1. Purpose and contract boundary

Phase 1 will deliver the authenticated NOVA application shell and browser workflows for:

- authentication and session handling;
- the current organization and the signed-in user's memberships/roles;
- project list, create, view, update, and delete;
- task list, detail, cancellation, and retry;
- result list, detail, metadata, and protected product delivery.

The only API source of truth for the frontend is `openapi/nova-browser-api.json`. The browser must use the existing same-origin BFF routes. It must not call the internal API directly, send `X-Internal-Secret`, retain OIDC provider tokens, or derive authorization from provider claims.

Phase 1 does **not** include AOI authoring, analysis submission forms, FIRRIS-specific scientific controls, billing, administration, engine management, or a GIS map renderer. Those areas require separate product and contract decisions. Their presence elsewhere in the repository or OpenAPI document does not make them part of this plan.

## 2. Architectural decisions

| Concern | Phase 1 decision |
|---|---|
| Browser/API topology | Same-origin browser requests to the BFF only |
| Routing | React Router with public, authenticated, and local error routes |
| Server state | TanStack Query |
| Form state | Component-local state or React Hook Form; server validation remains authoritative |
| Global client state | No Redux/Zustand initially; use router state, query cache, and small UI contexts |
| API typing | Generate TypeScript types from `nova-browser-api.json`; use a small typed BFF transport |
| Session persistence | Opaque HttpOnly cookie managed by the BFF; no browser token storage |
| CSRF | Keep the session-provided CSRF token in memory and attach it to unsafe methods |
| Authorization | The server is authoritative; role-aware UI only controls discoverability |
| Organization selection | Use the existing login flow with `organization_id`; do not invent a client-side switch endpoint |
| Task updates | Poll active tasks; stop polling at a terminal state |
| Protected products | Request same-origin product URLs using the session cookie |

## 3. Frontend route map

Routes marked "client-only" are navigation views backed by the listed existing APIs; they do not imply new backend endpoints.

| Frontend route | Access | Purpose | Existing contract(s) |
|---|---|---|---|
| `/login` | Public | Show provider readiness, explain sign-in, and start the full-page login flow | `GET /auth/config`, `GET /auth/session`, browser navigation to `GET /auth/login` |
| `/` | Authenticated | Resolve to `/projects` after session bootstrap | `GET /auth/session` |
| `/projects` | Authenticated | Project list and create entry point | `GET /api/v1/projects` |
| `/projects/new` | Role-aware authenticated | Project creation form | `POST /api/v1/projects` |
| `/projects/:projectId` | Authenticated | Project summary with links to its tasks and results | `GET /api/v1/projects/{project_id}` |
| `/projects/:projectId/edit` | Role-aware authenticated | Edit project metadata and, where permitted, delete the project | `PATCH /api/v1/projects/{project_id}`, `DELETE /api/v1/projects/{project_id}` |
| `/projects/:projectId/tasks` | Authenticated, client-only | Task list filtered by project | `GET /api/v1/tasks?project_id=...` |
| `/projects/:projectId/results` | Authenticated, client-only | Result list filtered by project | `GET /api/v1/results?project_id=...` |
| `/tasks` | Authenticated | Paginated task list with project, AOI, and status filters exposed only where supported by the schema | `GET /api/v1/tasks` |
| `/tasks/:taskId` | Authenticated | Task status, progress, timestamps, safe error summary, cancellation/retry actions, and result link | `GET /api/v1/tasks/{task_id}`, `POST /api/v1/tasks/{task_id}/cancel`, `POST /api/v1/tasks/{task_id}/retry` |
| `/results` | Authenticated | Paginated result list with supported filters | `GET /api/v1/results` |
| `/results/:resultId` | Authenticated | Result metadata, provenance, products, and protected delivery actions | `GET /api/v1/results/{result_id}`, `GET /api/v1/results/{result_id}/products/{product_key}` |
| `/forbidden` | Local | Explain an authorization denial without exposing resource existence | No endpoint |
| `*` | Local | Application not-found page | No endpoint |

`/auth/callback` is **not** a React route. It belongs to the BFF, which validates the authorization response, creates the server-side session, sets the opaque cookie, and redirects to the sanitized `return_to` location.

The first release should not add `/organizations/:id`, organization mutation routes, or an organization-switch API. The current contract exposes one selected organization plus memberships. Selecting another organization starts a new BFF login flow with the selected `organization_id` and the current relative URL as `return_to`.

### Route guard behavior

1. Bootstrap `GET /auth/session` before mounting authenticated routes.
2. While bootstrap is pending, render a neutral application loading boundary rather than the login page.
3. If `authenticated` is false, redirect to `/login` and retain only a validated relative return path.
4. If authenticated, load `GET /api/v1/organizations/current` before organization-dependent pages.
5. Role guards may hide or disable controls, but must never be treated as enforcement. Every mutation still relies on BFF/API authorization.
6. Treat cross-organization `404` responses as not found, without indicating that a concealed resource exists.

## 4. Component architecture

```text
src/
  app/
    AppRouter
    AppProviders
    AuthenticatedLayout
    PublicLayout
    RouteErrorBoundary
    NotFoundPage
    ForbiddenPage
  features/
    auth/
      LoginPage
      SessionBootstrap
      RequireSession
      LogoutAction
      AuthConfigurationNotice
    organization/
      OrganizationContextProvider
      CurrentOrganizationBadge
      OrganizationMenu
      MembershipList
      RoleBadge
    projects/
      ProjectListPage
      ProjectDetailPage
      ProjectCreatePage
      ProjectEditPage
      ProjectTable
      ProjectForm
      ProjectDeleteDialog
    tasks/
      TaskListPage
      TaskDetailPage
      TaskFilterBar
      TaskTable
      TaskStatusBadge
      TaskProgress
      TaskTimeline
      TaskActions
      TaskErrorSummary
    results/
      ResultListPage
      ResultDetailPage
      ResultFilterBar
      ResultTable
      ResultSummary
      ResultMetadataPanel
      ResultProvenancePanel
      ResultProductList
      ProtectedProductAction
  shared/
    api/
      generated/
      client
      csrf
      errors
      queryKeys
    ui/
      AppShell
      DataTable
      Pagination
      EmptyState
      LoadingState
      ErrorState
      ConfirmDialog
```

This is a responsibility map, not a requirement to create one file for every label. Components should be split only when they own distinct behavior or are reused.

### Component rules

- Page components coordinate routing, queries, mutations, and page-level error handling.
- Feature components receive typed domain data and callbacks; they do not construct URLs or make ad hoc fetches.
- `shared/api/generated` is generated and never edited manually.
- `shared/api/client` is the sole place for request credentials, CSRF middleware, and normalized transport errors.
- Organization and role displays use values returned by the BFF/API. They never infer access from email domain, OIDC claims, provider groups, or provider roles.
- The task UI uses only the documented lifecycle values: `queued`, `running`, `completed`, `failed`, and `canceled`.
- The result UI treats `summary`, `provenance`, and GIS metadata as contract data. It must not assume undocumented FIRRIS-specific shapes or reveal storage paths.
- Product delivery uses the returned product identity and protected endpoint. It must not build filesystem or object-store locations.

## 5. API client generation approach

### Source and generated output

Use `openapi/nova-browser-api.json` as the single input to a pinned `openapi-typescript` version. Generate the schema into a clearly marked file such as:

```text
src/shared/api/generated/nova-browser-api.d.ts
```

Use `openapi-fetch` as the lightweight typed transport over those generated paths and operations. This keeps request and response types generated while leaving the BFF-specific browser policy explicit and reviewable.

The frontend repository should provide two scripts when implementation begins:

- `api:generate`: regenerate types from the checked-in browser OpenAPI document;
- `api:check`: regenerate in CI and fail if the committed generated artifact differs.

No generated client may use the internal API OpenAPI document. Generation must fail on an invalid or missing browser schema rather than silently falling back to untyped requests.

### Transport policy

Configure one client with:

- an empty/same-origin base URL;
- `credentials: "include"` on every request;
- `Accept: application/json` by default;
- `X-CSRF-Token` only on `POST`, `PUT`, `PATCH`, and `DELETE` requests, using the current in-memory session value;
- no authorization bearer header;
- no `X-Internal-Secret` support;
- no provider-token support.

Protected binary products should use a dedicated helper that preserves the same-origin cookie and honors `Content-Type` and `Content-Disposition`. A normal browser navigation/download is preferred when no client-side error body is needed; otherwise the helper may fetch a Blob and surface a normalized API error.

### Contract adaptation

The browser contract currently contains both aliased camel-case session fields (for example `csrfToken` and `displayName`) and snake-case organization/resource fields (for example `current_organization`, `organization_id`, and `created_at`). The client must consume the generated names exactly.

Small feature-boundary adapters may expose consistent view models, but they must be typed, deterministic, and covered by tests. A global key-renaming interceptor would obscure the actual contract and should not be used.

### Error model

Normalize transport failures into a frontend error type containing HTTP status, public code, public message, detail, and request correlation data if the response supplies it. Preserve the server's stable error envelope; never render raw response bodies or stack traces.

Page behavior should be:

| Status | Frontend behavior |
|---|---|
| `400` | Show the public request error near the action |
| `401` | Clear session-derived query data and return to login with a relative `return_to` |
| `403` | Refresh the session/CSRF value once if appropriate, then show a permission error; do not repeatedly retry |
| `404` | Show not found without disclosing tenant/resource existence |
| `409` | Show the domain conflict, such as an invalid task transition or blocked project deletion |
| `422` | Map validation details to form fields where possible and show a form summary |
| `429` | Preserve the user's input and ask them to retry later |
| `502`/`504` | Show a temporary service failure and a deliberate retry action |

## 6. Authentication and organization flow

```text
Browser loads React app
  -> GET /auth/session
     -> unauthenticated: render /login
     -> authenticated: cache user, selected organization, roles, csrfToken
  -> GET /api/v1/organizations/current
  -> render organization-scoped application

User chooses Sign in
  -> full-page GET /auth/login?return_to=<relative path>
  -> BFF performs OIDC Authorization Code + PKCE flow
  -> provider returns to BFF-owned /auth/callback
  -> BFF validates response and creates Redis-backed opaque session
  -> BFF sets HttpOnly session cookie and redirects to return_to
  -> React repeats session bootstrap

Unsafe browser mutation
  -> session cookie sent automatically
  -> X-CSRF-Token populated from current session response
  -> BFF validates session and CSRF
  -> BFF injects trusted internal credentials server-side

Logout
  -> POST /auth/logout with session cookie and X-CSRF-Token
  -> BFF invalidates server-side session and deletes cookie
  -> React clears all query data and navigates to /login
```

### Security requirements for the frontend

- Never store the session, CSRF token, provider tokens, roles, or membership data in `localStorage`.
- Never place secrets in `VITE_*` variables or shipped configuration.
- Never process an OIDC authorization code in React.
- Never grant access based on an email domain, provider group, provider role, or arbitrary tenant claim.
- Never trust a hidden/disabled button as authorization.
- Sanitize `return_to` as a relative in-app path before using it in a login URL.
- Avoid logging session payloads or error response internals to browser telemetry.
- Re-bootstrap the session after login, logout, a `401`, and organization reselection.

Membership changes are ultimately enforced by protected backend requests. If a previously authenticated user's account or membership becomes disabled, a protected API denial must replace stale client assumptions. The frontend should clear affected organization data and present a re-authentication/support path rather than continuing from cached permissions.

## 7. State management plan

### Server state

TanStack Query owns all API-derived state. Suggested query keys are:

```text
["auth", "config"]
["auth", "session"]
["organization", "current"]
["projects", filters]
["projects", projectId]
["tasks", filters]
["tasks", taskId]
["results", filters]
["results", resultId]
```

Query keys must include every server-side filter and pagination parameter. Project/task/result filters and pagination belong in URL search parameters so views are bookmarkable and browser navigation is predictable.

### Mutation and invalidation policy

| Mutation | On success |
|---|---|
| Create project | Invalidate project collections, cache returned project, navigate to its detail page |
| Update project | Replace/invalidate project detail and project collections |
| Delete project | Remove detail cache, invalidate collections, navigate to `/projects` |
| Cancel task | Invalidate task detail and matching task collections |
| Retry task | Invalidate collections and navigate to the newly returned task identity if supplied by the contract |
| Logout | Clear the entire query cache and navigate to `/login` |

Do not optimistically alter task lifecycle or result availability. For the first release, also wait for confirmed project mutation responses rather than adding optimistic edits; conflict and authorization responses carry important domain meaning.

### Task polling

- Poll `queued` and `running` task detail approximately every two seconds.
- Stop polling for `completed`, `failed`, or `canceled`.
- Slow or suspend polling when the document is hidden.
- Do not poll result detail until the task/result contract identifies a result.
- Use bounded retry/backoff for transient network failures; do not retry authorization, validation, or conflict errors automatically.

### Local and navigation state

- React Router owns the current route, resource IDs, filters, pagination, and post-login return location.
- Component state owns dialogs, menus, form drafts, table selection, and disclosure panels.
- A small UI context may own shell-only concerns such as navigation collapse or notifications.
- Authentication and organization data remain query state, not duplicated mutable context state. Context may expose selectors/actions over those queries.
- No general-purpose global state library is needed unless a later phase introduces cross-route unsaved GIS edits or another demonstrable client-state requirement.

## 8. Existing contract usage

### Session

`GET /auth/session` is the safe bootstrap request. An unauthenticated response is normal and should render the public login state rather than a global error. The authenticated response supplies the current user, selected organization, roles, and `csrfToken`.

### Organization

`GET /api/v1/organizations/current` supplies the durable current user, current organization, current role, and memberships. It is the source for organization chrome, membership display, and role-aware controls. The session response is used for fast bootstrap and CSRF; the organization response is used for the complete organization view.

### Projects

Use the collection and item contracts without adding client-only persistence. Creation exposes only documented request fields. Updates expose only documented mutable fields. Deletion must require confirmation and correctly present a `409` when backend dependencies prevent deletion.

### Tasks

Tasks are the canonical job lifecycle. Lists must use server pagination/filtering. Detail views show progress and timestamps, and render only the public `error_summary`/safe error field. Cancellation and retry actions are available only for states and roles in which the backend accepts them; the UI must still handle rejected transitions.

### Results

Result pages use the persistent result APIs, not task payloads as a substitute. Render the documented metadata, summary, provenance, and product descriptors. Product delivery always uses the protected result-product contract and the existing session cookie.

## 9. Implementation sequence

### Increment 1: foundation and generated contract

- Establish the React/TypeScript application structure.
- Add schema generation and CI drift checking from `nova-browser-api.json`.
- Add the same-origin typed client, public error normalization, and query-key factory.
- Add router, query provider, app shell, and top-level error boundaries.

Exit criterion: a contract drift check runs deterministically, and no frontend configuration accepts an internal secret or provider token.

### Increment 2: authentication and organization shell

- Implement session bootstrap, login navigation, logout, and CSRF middleware.
- Add authenticated routing and return-path handling.
- Load current organization, memberships, and roles.
- Add organization display/reselection through the existing login flow.

Exit criterion: login, refresh, logout, expired-session recovery, CSRF rejection, and disabled membership behavior work through the BFF.

### Increment 3: project lifecycle

- Implement list, create, detail, edit, and confirmed deletion.
- Add role-aware controls and server-driven error handling.
- Link project detail to client-side filtered task and result views.

Exit criterion: project CRUD works for authorized roles and cross-organization access remains denied by the backend.

### Increment 4: task lifecycle

- Implement filtered/paginated lists and detail pages.
- Add terminal-state-aware polling.
- Add cancellation and retry with conflict/error handling.

Exit criterion: queued-to-terminal transitions render correctly and stale/invalid mutations do not produce optimistic false state.

### Increment 5: result discovery and protected delivery

- Implement result list and detail views.
- Render GIS metadata, summary, provenance, and product descriptors without assuming undocumented shapes.
- Implement protected product retrieval/download.

Exit criterion: an authorized browser can retrieve a result product, while an unauthorized organization cannot discover or download it.

### Increment 6: hardening and staging acceptance

- Add accessibility, responsive layout, empty/loading/error states, and telemetry redaction.
- Run contract, component, route, and staging end-to-end tests.
- Verify that built assets contain no internal secret, provider token, or internal API origin.

## 10. Verification plan

### Contract and unit tests

- Generated types are current with the checked-in browser OpenAPI document.
- Request middleware sends cookies and adds CSRF only to unsafe methods.
- Error normalization handles the public envelope and non-JSON gateway failures.
- View-model adapters cover the contract's camel-case/snake-case boundary.
- Permission selectors affect presentation only and do not bypass API requests.

### Component and route tests

- An unauthenticated session renders `/login` and preserves a safe relative return path.
- An authenticated session enters the organization-scoped shell.
- Session expiry clears protected cached data.
- Project forms map `422` errors and deletion maps `409` conflicts.
- Task polling stops for every terminal status.
- Task cancel/retry refreshes the correct list and detail queries.
- Result products use the protected endpoint rather than a storage path.
- `403`/`404` views do not disclose cross-organization resource information.

### Staging end-to-end tests

- OIDC sign-in returns through the BFF-owned callback and restores the requested app route.
- Refresh retains the opaque server-side session without browser token storage.
- Logout invalidates the session and blocks protected navigation.
- Organization reselection establishes the selected server-side context.
- Authorized project, task, result, and product flows succeed.
- Unauthorized organization access fails for project, task, result, and product requests.
- A disabled user or revoked membership loses protected access despite previously rendered UI.

## 11. Phase 1 entry assumptions and explicit blockers

Phase 1 can begin against the current contracts for the scoped shell, organization context, projects, tasks, and results. Before implementation starts, the frontend project must decide only repository-level concerns such as its location, package manager, supported browsers, and visual design system.

The following are deliberately not solved by this plan and must not be improvised during Phase 1:

- AOI creation/editing and spatial validation UX;
- FIRRIS analysis parameter and submission contracts;
- map tile, vector, raster/COG, preview, and legend rendering behavior;
- billing and entitlement management UI;
- invitation and administrator workflows;
- client-side organization membership mutation;
- MEGIS, WRAS, or other engine-specific experiences.

These are later-phase capabilities. Phase 1 should expose links or controls for them only after their browser contracts and product requirements are explicitly approved.
