# Stage C dynamic acceptance — PostgreSQL roles and Redis AUTH (2026-10-30)

This closes the "dynamic PostgreSQL/Redis acceptance is pending" line from
Stages C/D1. It is an acceptance receipt for the already-pushed configuration
in `fb1e077`; no application code changed for it.

## Environment

- Docker engine `29.8.2` became available again; the live `nexus_net` stack was
  left untouched.
- Disposable containers only: `pgvector/pgvector:pg16` and `redis:7-alpine`,
  bound to `127.0.0.1` on throwaway ports.
- Credentials for the run were generated per container and deleted afterwards.
  None are recorded here or in the repository.

## Fresh volume (init scripts)

`init-scripts/01-create-databases.sql` and `02-create-service-roles.sh` were
mounted as a first-boot init directory:

| Check | Result |
| --- | --- |
| Three service roles created on first boot | 3/3 |
| Database owners | `authfortress=auth_service`, `webhook_manager=webhook_service`, `agenthub=agent_service` |
| `auth_service` → `authfortress` | `auth_service@authfortress` |
| `auth_service` → `webhook_manager` | `permission denied for database` |
| `webhook_service` → `webhook_manager` / → `agenthub` | allowed / `permission denied for database` |
| `agent_service` → `agenthub` / → `authfortress` | allowed / `permission denied for database` |
| Unrelated LOGIN role → `authfortress` | `permission denied for database` (`REVOKE CONNECT ... FROM PUBLIC`) |
| Alembic `upgrade head` as `auth_service` | 4 revisions applied, `alembic check` clean |
| Alembic `upgrade head` as `webhook_service` | 9 revisions applied, current `c42d8e91a730` |
| Alembic `upgrade head` as `agent_service` | 3 revisions applied |

Redis with `--requirepass`:

| Check | Result |
| --- | --- |
| `redis-cli ping` without credentials | `NOAUTH Authentication required.` |
| `REDISCLI_AUTH=<password> redis-cli ping` (healthcheck form) | `PONG` |
| wrong password | `AUTH failed: WRONGPASS` |

## Existing volume (`scripts/provision-service-db-roles.sh`)

A second disposable instance was initialised with the database DDL only, then
migrated as the superuser so tables, enums and `alembic_version` were owned by
`accept_root` — the legacy-volume state.

- First run reassigned schema, table and database ownership to the three service
  roles; the script exits 0 when invoked as documented
  (`docker exec ... sh /tmp/provision.sh` with the three password variables).
  Piping the script into `sh -s` adds a phantom trailing line and exits 127 —
  use the documented file form.
- Re-run from a superuser-owned table state exits 0 and restores
  `tableowner=auth_service`, so the operation is idempotent.
- After provisioning, each role could `CREATE TABLE` / `INSERT` / `DROP TABLE`
  in its own database, while `auth_service` → `agenthub` and
  `agent_service` → `webhook_manager` remained `permission denied for database`.
- Enum type ownership was reassigned with the tables (the AuthFortress schema
  uses enum columns).

## Not covered

- The live stack was not restarted and no existing volume was modified. Rollout
  still needs the deployment step from `specs/infra-auth.md`.
- WebHook Manager's local working tree carries an untracked migration
  (`8f3b1c6d2a90`) that creates a second Alembic head. The acceptance above ran
  against the committed tree extracted from `HEAD`, which has a single head;
  `alembic upgrade head` would fail while that untracked file is present.
- Per-service Redis ACLs, network segmentation and TLS remain out of scope, as
  recorded in the Stage C residual list.
