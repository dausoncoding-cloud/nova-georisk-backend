# Administration and external data management

This bundle extends the existing Browser → gateway/BFF → FastAPI architecture. It does not deploy to production, provision an Auth0 application, enable bootstrap, change strict membership policy, or change FIRRIS formulas. Existing unrelated scientific working-tree changes are preserved. No commit or push is performed.

## Organization access

Authentication remains an exact, verified OIDC issuer/subject identity. NOVA database memberships remain the authority for organization access; provider groups and email domains do not assign roles.

| Role | Read project datasets | Upload/manage own versions | Scientific review | Organization administration |
| --- | --- | --- | --- | --- |
| viewer | Yes | No | No | No |
| analyst | Yes | Yes | No | No |
| admin | Yes | Yes, including other uploaders | Yes, another uploader's sources | Manage viewer/analyst memberships only |
| owner | Yes | Yes, including other uploaders | Yes, another uploader's sources | Manage all four role types |

The role values remain exactly `viewer`, `analyst`, `admin`, `owner`. Administrative endpoints require a current database-backed user context, not the internal service secret alone. Tenant IDs must match the current organization. Requests with stale role assertions or inactive users/memberships are denied. The same membership-state check protects existing project/engine APIs, organization context and strict OIDC membership resolution.

Membership states are `active`, `disabled`, `removed`. Disable/removal is organization-scoped; it never deletes the User, Auth0 account, membership history, task ownership or Result records. Restoration is explicit and subject to the same role boundaries. The product does not enable globally disabled NOVA users or change provider accounts. Existing cookies are denied while membership is inactive; changed roles require a fresh sign-in.

Self-directed access mutations are forbidden, including self-promotion and self-removal. Organization-row locks serialize role changes. Owner-demotion/removal checks count active owners, and concurrent owners cannot demote one another into an ownerless organization. The self-change restriction also protects the final owner's own membership.

### Identity provisioning and invitations

Administrators preprovision an exact known OIDC issuer/subject after obtaining an identity-verification reference from the identity administrator. The issuer must match the configured provider. This creates or associates a NOVA identity/membership; it does not create an Auth0 account or independently query/attest provider-directory existence. Email/display name are descriptive and never replace the durable issuer/subject key. Existing identity attributes are not overwritten by an organization administrator. A verification-reference hash is audited; no provider credential is collected. The register shows membership creation/update dates, not an invented last-login timestamp.

The invitation page is a read-only register of up to 100 existing invitations, with pending/expired/redeemed status. This bundle does not create invitation tokens or add a redemption flow. Strict production policy remains intact. For redeemed invitations, `access_granted` is unknown/null rather than inferring current access from an email address. Invitation history is not evidence of current membership; current access is shown in Users & memberships.

## Immutable audit

Successful access mutations create an audit event in the same transaction as the change. Events record actor, target user when applicable, organization, action, previous/new role and state, UTC timestamp, and a bounded UUID correlation ID when available. Membership events identify an applied result. Failed requests do not manufacture successful changes; existing safe HTTP error handling remains in effect.

Dataset upload, metadata, validation, review and archive actions also append events, using version IDs/statuses/checksums rather than file contents. PostgreSQL rejects UPDATE, DELETE and TRUNCATE of audit rows through an immutable-audit trigger. No mutation endpoint edits/deletes audit history. Database superuser access is outside this application control; retain normal database operational safeguards.

Passwords, provider tokens, session cookies and client secrets are not audit fields. The UI shows old/new access values and actor/target IDs; membership history can be filtered by target user.

## External dataset catalogue and formats

The existing versioned FIRRIS catalogue is reused: **40 category profiles**, comprising 9 CSV, 12 GeoJSON and 19 GeoTIFF profiles. Supported formats are category-specific, not interchangeable extensions.

- Hydrology/hydraulics: rainfall, river-stage/discharge stations, stage thresholds, hydraulic cross sections, water-surface elevation, hydraulic model velocity.
- Historical/terrain/watershed/soil: historical flood events, annual inundation, inundation slices, terrain DEM, river/drainage network, watershed outlets, soil permeability/texture, land cover and administrative boundaries.
- Exposure: population density, buildings, roads, critical infrastructure, economic assets, cropland fraction and livestock density. Catalogue inventory metadata distinguishes applicable asset types.
- Vulnerability/capacity: vulnerability indicators and community-capacity indicators with reviewed spatial units, directions and units.
- Validation/decision support: independent observations; continuous/binary observations and predictions; probabilities, uncertainty/folds; predictor observations/rasters; flood-impact/DSS records; sensor registry and reviewed zonation policy.

CSV is UTF-8 with unique catalogue headers, bounded nonempty records and no undeclared fields. GeoJSON uses supported geometry and catalogue attributes. TIFF uploads must be readable single-band GTiff with valid CRS/north-up transform and supported numeric dtype. Declared raster band identity must match the TIFF band description before a version proceeds to scientific review. All registered sources pass the existing category-specific validators.

**Not advertised as supported:** Shapefile ZIP, GeoPackage, KML, arbitrary ZIP/archives or arbitrary new dataset categories. Archives are rejected before extraction, so traversal members and archive bombs cannot be unpacked. Existing AOI import support for other formats does not imply scientific dataset support. Specialized inputs not represented by the catalogue need a separately reviewed parser/profile/adapter; no placeholder scientific capability is claimed.

## Metadata and lifecycle

Metadata is entered explicitly through structured fields and, for specialized category requirements, an expandable JSON manifest. Missing values are never imputed. Required scientific information includes source identifier, producer/custodian, acquisition/coverage dates with timezones, CRS, applicable datum/units/resolution, coverage, licence/use/redistribution, documented source QA, positional uncertainty where applicable and quantitative uncertainty. Null/not-applicable declarations are explicit. Additional catalogue fields include indicator definitions, class schemes, hydraulic model/evidence references, observation cadence and reviewed method definitions.

The server binds project, category and SHA-256 to the stored version. User-supplied identity/checksum mismatches are rejected. Descriptive management notes capture contact, temporal resolution, original source version, quality and change notes; they do not substitute for scientific requirements or drive formulas.

| State | Meaning |
| --- | --- |
| Uploaded | Private immutable bytes recorded; not scientifically usable |
| Needs Metadata | Manifest is incomplete/inconsistent; field diagnostics are returned without echoing upload contents |
| Needs Scientific Review | Structurally valid (`structurally_valid=true` in the report), registered, and awaiting review; this is not approval |
| Approved for Analysis | A different organization admin/owner attested the required scientific checks and evidence |
| Rejected | Structural validation or scientific review rejected this version; reason is retained |
| Archived | Logically withdrawn; bytes and historical references remain, and new analysis use is blocked |

Structural validity is a report flag, not a second approval state. Metadata remains editable before a scientific source registration exists. Once registered, metadata/AOI association is frozen; revisions require a new version. A replacement receives a new UUID, monotonically increasing series version and separate source registration. Prior versions and task/Result lineage are not rewritten. Archive uses DELETE semantics without physical deletion.

Scientific approval requires the existing `SourceReadinessReview`: six mandatory true attestations plus evidence references, with additional category/module checks where applicable. Self-approval is blocked. Approval/rejection/revocation is audited. Managed sources cannot bypass this lifecycle through the legacy source-approval endpoint.

## Analysis eligibility and history

The Usage tab reports candidate FIRRIS modules and target AOI/period compatibility. It distinguishes an approved candidate input from an executable/ready product. Incomplete target context, unapproved state, checksum failure, different attached AOI, insufficient declared spatial coverage or insufficient temporal coverage block compatibility.

Production source-bound workflows continue resolving exact approved source IDs through the existing binding contract. They revalidate bytes/checksum, structural format, review evidence, time/space, source roles, CRS/datum and module-specific scientific requirements. Managed source status and optional AOI scope are enforced there as well. The existing satellite/GEE builder is not silently changed to consume arbitrary uploads; its contextual link opens vetted-input management for advanced workflows.

The approved-version selector excludes unapproved/rejected inputs. An optional full-binding preflight calls the existing protected scientific validator without creating a task; it reports the server result rather than assuming executability.

A file upload never unlocks depth/velocity/hazard, AEP/return period, exposure, FVI/FII/CRI, susceptibility or external validation by itself. Those paths retain required companions, upstream results, sample support and quality gates. Source IDs, checksums, scientific metadata and managed version identity remain pinned in task lineage. Physical bytes and original snapshots remain available for historical inspection.

## Storage and upload security

- New endpoints require tenant-scoped active membership and project/engine authorization. Analysts modify their own uploads; admins/owners can manage other uploaders' versions. Only admins/owners review scientific readiness.
- Maximum file size is **16 MiB**; metadata is bounded at 64 KiB. Existing gateway request limits remain. CSV/vector count is bounded at 100,000; raster dimensions are bounded at 4,000,000 cells before pixel decoding.
- Plain supported filenames are required, but original filenames are never used as storage keys. Server UUID keys include organization/project scope; files use mode 0600 and managed directories 0700. Downloads use generated attachment names, authenticated endpoints, no-store and nosniff headers; no public URL is added.
- File/metadata credential markers, unsupported archives/executables, malformed records/geometry, non-finite metadata and unsafe TIFFs are rejected. Stored bytes are rechecked by SHA-256 before download or validation.
- Protected storage must be outside real source checkouts and Python source directories. The existing runtime artifact volume (normally `/app/outputs`) is reused by API/workers; do not configure a checkout-local output directory for this feature.
- Docker context exclusions and Git ignore rules additionally exclude `external-datasets`. No uploaded dataset, validation fixture content or browser profile is packaged in production images or committed.
- Retention is logical; physical garbage collection, institution-wide retention/legal-hold policies, antivirus service integration, aggregate storage quotas and a separate upload-processing queue are future operational work. Parsing is bounded and uses the existing trusted format parsers; no claim of an external malware scanner is made.

## API changes

All paths are under `/api/v1`, traverse the existing BFF, and use existing session/CSRF and error contracts.

| Path suffix | Methods / behavior |
| --- | --- |
| `/organizations/{organization_id}/administration/memberships` | GET search/filter/pagination; POST exact-identity provisioning |
| `/organizations/{organization_id}/administration/memberships/{user_id}` | PATCH role/state, including disable/remove/restore |
| `/organizations/{organization_id}/administration/audit` | GET paginated immutable events, optional target user |
| `/organizations/{organization_id}/administration/invitations` | GET historical invitation register |
| `/projects/{project_id}/external-datasets` | GET search/type/status/pagination; POST private multipart upload with draft JSON manifest |
| `/projects/{project_id}/external-datasets/contract` | GET upload/scientific JSON schemas, actual supported formats and byte limit |
| `/projects/{project_id}/external-datasets/{dataset_id}` | GET version detail; DELETE logical archive |
| `.../{dataset_id}/metadata` | PATCH draft metadata / optional project AOI attachment |
| `.../{dataset_id}/validate` | POST structural validation and frozen scientific source registration |
| `.../{dataset_id}/review` | POST approve/reject/revoke with reason and required evidence |
| `.../{dataset_id}/versions` | GET series history |
| `.../{dataset_id}/download` | GET protected original bytes |
| `.../{dataset_id}/eligibility` | GET approval and target AOI/time compatibility, candidate modules |
| `.../{dataset_id}/usage` | GET bounded historical analysis references |

The browser contract grows from **64 to 78 paths**; internal from **59 to 73**. The 14 new paths contain 17 HTTP operations. No existing path definitions are removed or changed. Backend-exported schemas and generated frontend types remain synchronized. Existing legacy source approval/revocation rejects managed versions with 409 and directs callers to the audited review route.

## Frontend

- Administration: role-protected navigation/route, searchable and filtered Users & memberships table, issuer/subject disclosure, explicit role/state confirmation, exact-identity provisioning, invitation register and paginated audit/history.
- External data: global project selector and project Data workspace, Datasets/Upload/Validation/Usage/Provenance tabs, compact filters/tables, review-before-private-storage, structured scientific metadata, explicit validation/review, versioning and protected downloads.
- Shared confirmation dialog reuses focus containment, Escape and focus restoration; shared tabs, pagination, disclosures, table/mobile and form styles are retained.

## Migration and rollback implications

Migration **`f1a2b3c4d5e6`**, based on production head **`e8b5c2a71f40`**, adds:

1. Non-null membership `status`, server-default active and a check constraint.
2. `access_audit` plus immutable PostgreSQL trigger/function.
3. `managed_datasets`, immutable source/version links and indexes/constraints.

The populated upgrade test preserved 18 pre-existing rows across 16 old tables and verified active legacy memberships plus the audit trigger. No production migration was run.

Destructive Alembic downgrade is intentionally refused to preserve audits and dataset history. Application rollback must retain membership-status enforcement: an old backend/BFF that ignores disabled/removed status is **not a safe rollback** after revocation. Use a compatible recovery build/forward fix. Do not delete membership/history rows or restore an unaware old binary to bypass this restriction. Older frontend assets can be restored independently while retaining compatible API/BFF guards.

Before production rollout, take normal database/artifact backups and drain/quiesce outstanding work. Apply the additive migration and deploy matching compatible API/BFF/worker code and frontend, and perform real administrator/analyst/browser acceptance. The execution fingerprint covers all application Python source: old queued tasks must not silently run on changed code, and API/worker images must match.

This task prepares and verifies code locally; it does not perform that rollout or assert that the earlier production reachability incident was resolved.

## Verification

Verification is local and uses synthetic disposable fixtures only; no external dataset or production task is fabricated.

| Check | Result |
| --- | --- |
| Complete backend unit suite | 797 passed |
| Complete PostGIS integration suite | 171 passed |
| Final management security/integration recheck | 49 passed (37 unit + 12 PostGIS integration) |
| Populated Alembic upgrade e8b5c2a71f40 → f1a2b3c4d5e6 | Passed; 16 existing tables / 18 rows preserved |
| Frontend unit/component/transport suite | 98 passed across 26 files; regenerated final types; typecheck passed |
| Typecheck, contract check and production frontend build | Passed: Node 22 typecheck, generated API check, tsc/Vite production build |
| Production Docker images / layer packaging scans | Both built; backend zero findings; frontend two exact public-CA symlinks reviewed, zero unresolved findings |
| Responsive Chromium acceptance | 45 checks passed: 9 views/dialogs × 1440/1024/768/390/320px |
| Existing OpenAPI definitions | All 59 internal / 64 browser path definitions identical to HEAD |
| Whitespace checks | Backend and frontend passed |

Backend tests use the isolated local PostGIS container, bounded BLAS thread counts and an outside-checkout artifact directory. TestClient/local-network tests require the host-enabled execution environment; restricted socket execution is not a test result. Frontend checks use Node 22 and a single-fork Vitest resource profile, with the existing setup and explicit cleanup retained. Existing deprecation warnings do not fail these suites.

Browser checks use synthetic same-origin API fixtures in headless Chromium. They exercise administration, invitations, audit, access dialog, and the five dataset tabs at 1440/1024/768/390/320px, including overflow, dialog containment and Escape behavior. They do not assert real Auth0 login, production availability, or live scientific approval.

## Changed file inventory

Backend adds `app/models/management.py`, `app/schemas/management.py`, administrative/external-data endpoint modules, `app/services/access_management.py`, `app/services/external_data.py`, the additive migration and security/integration test modules. Existing identity/membership guards, API routing, source readiness/bindings, packaging exclusions and both OpenAPI exports are updated. Existing unrelated scientific changes are excluded from this bundle's ownership.

Frontend adds `src/features/management/` with AdministrationPage, ExternalDataPage, MetadataEditor, ConfirmDialog, generated-contract API adapter and three test modules. Router, navigation, analysis context link, shared styles, browser OpenAPI/types and Docker exclusions are updated. No dependency change is required. The earlier untracked frontend rollout report is preserved.

## Remaining operational and scientific limitations

- No production migration/deployment or live acceptance is included. Deploy matching API/BFF/workers and frontend only after normal environment/storage/backups and queue-drain checks.
- Invitation tooling is an existing-history register, not invitation creation/redemption; strict provisioning remains authoritative.
- Formats outside the three parsed catalogue formats and scientific inputs without an existing reviewed profile are not supported.
- Approval is human scientific attestation plus existing deterministic gates, not proof of dataset truth or automatic product readiness. A second authorized reviewer is required.
- Aggregate quotas, asynchronous ingestion, institutional retention policy and external antivirus integration remain operational extensions. Bounded parsing and credential-marker checks do not claim full malware detection.
- Historical usage is an exact-source-ID view bounded to the latest 100 references; old versions/bytes and task lineage are retained.

No commit, push, production traffic change or provider credential change was performed.


### Final local image identities

- Backend `nova-georisk-backend:management-review`: `sha256:e0bbd76bd049da07f484ae8257a0472793297e6f186bcb4f6ffa5d6fd9298f7c`.
- Frontend `nova-georisk-frontend:management-review`: `sha256:1a9503d6f8d064c2e446ace3173572297f5a3d1aedc43e95f0ce1b459443db02`.
- Backend host/image implementation fingerprint matches exactly: `9b0a7e16c559e6e406bbbbd96415f9912e2fae28f29050e37c816e41368221e5` (all application Python plus requirements, including the preserved pre-existing scientific working-tree changes).
- Backend all-layer scan: 13 layers, 25,588 files, 45 reviewed dependency matches, zero findings. Frontend all-layer scan: 9 layers, 1,050 files; two raw findings, both reviewed public-CA symlinks; zero unresolved findings. Nginx syntax and static asset/source-map checks passed.

These are local working-tree build image IDs, not published registry digests or a committed release. Raw verification logs and scan evidence remain under `/tmp/nova-management-*`; the images are retained for review. Disposable preview/database services are stopped. Production is untouched.


The frontend raw scanner flags `etc/ssl/cert.pem` and `etc/ssl1.1/cert.pem` by extension. Exact layer-0 review follows only those two known links to `etc/ssl/certs/ca-certificates.crt` and verifies the public bundle SHA-256 `756cdfe4c3affc2e460278cc65ab01f67c3f4fc05d43fc683d7ebbdeb644e5f4`, with no private-key/service-account markers. The raw report and separate bounded review remain available; no backend packaging policy was changed and no unresolved finding was suppressed. This is a layer/secret-packaging scan, not a claim of CVE-free dependencies or external malware scanning.

Final classification: **ADMIN & EXTERNAL DATA MANAGEMENT COMPLETE** (implementation and local verification; production rollout remains a separate operation).
