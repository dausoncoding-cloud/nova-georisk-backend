# FIRRIS canonical-name migration plan

## Decision

`FIRRIS` is the official platform name and `firris` is the canonical engine key. The
shared browser execution endpoint is `/api/v1/analyses`; future MEGIS and WRAS adapters
will use the same task/result contract.

## Safe compatibility boundary

- Existing scientific Python modules under `app/services/firas` are retained. Renaming
  import paths would add risk without changing platform behavior or scientific results.
- Existing `/api/v1/firas/*` synchronous calculator URLs are retained as legacy API
  compatibility routes. They now authorize against the canonical `firris` entitlement.
- The historical `TaskType.FIRAS_INDEX` enum value is retained for old task rows. New
  persistent executions use the engine-neutral `analysis` task type.
- Historical documentation and the pre-Phase-0 migration fixture remain historical
  records. Current contracts and operational instructions must use FIRRIS.

## Database migration

Migration `c7f0a8d42e91` copies the engine registry rows before repointing foreign keys,
then changes `firas` to `firris` and `wrras` to `wras`. Projects, tasks, results,
entitlements, and billing-plan links keep their existing ownership and IDs. Project
`analysis_module=FIRAS` becomes `FIRRIS`. No production migration is executed by this
change set.

The migration also adds the required PostgreSQL enum values `ANALYSIS` and `CANCELED`
and removes the obsolete uniqueness rule on engine route namespaces so all engines can
share `/api/v1/analyses`.

## Deployment order

1. Back up and dry-run the migration on a staging copy.
2. Verify no independently-created `firris` or `wras` rows conflict with legacy rows.
3. Deploy API and worker code together with the migration.
4. Verify entitlement discovery, legacy calculator compatibility, new submissions,
   cancellation/retry, and protected downloads.
5. Update external operational tooling from `firas` to `firris`.
6. Deprecate legacy calculator URLs only after all consumers have migrated; removing
   them is explicitly outside this phase.
