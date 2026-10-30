# Infrastructure authentication (Stage C)

## Redis

Redis now starts with `--requirepass` using a required `REDIS_PASSWORD`. Every
`REDIS_URL` and `CELERY_BROKER_URL` carries the password, and the healthcheck
uses `REDISCLI_AUTH` rather than an unauthenticated `PING`. The host port stays
loopback-bound.

All AgentHub, WebHook and AuthFortress keys remain in the same Redis instance;
database numbers are not a security boundary. Per-service Redis ACLs are a
follow-up when Celery key/command patterns are reviewed; the immediate defect
(unauthenticated Redis on the shared bridge and loopback port) is closed.

Passwords must be URL-safe because Compose interpolates them into URL userinfo.
`.env.example` leaves `REDIS_PASSWORD` empty so Compose fails before startup
until an operator supplies one.

## PostgreSQL

The `postgres` container still uses `POSTGRES_USER`/`POSTGRES_PASSWORD` as the
initialization superuser. Runtime services no longer use that superuser:

| Service | Role | Database |
|---|---|---|
| AuthFortress | `auth_service` | `authfortress` |
| WebHook Manager (API, worker, recovery, sender) | `webhook_service` | `webhook_manager` |
| AgentHub (API, worker, recovery) | `agent_service` | `agenthub` |

Fresh volumes run `init-scripts/01-create-databases.sql` then
`init-scripts/02-create-service-roles.sh`: roles are created (idempotently),
each database is owned by its service role, `CONNECT` is revoked from `PUBLIC`,
and only the service role receives it. The role owns its database and can run
Alembic migrations; the `vector` extension is still created by the superuser in
`01`. The `postgres` service must receive the three role passwords in its own
environment; Compose now requires them (`AUTH_DB_PASSWORD`,
`WEBHOOK_DB_PASSWORD`, `AGENT_DB_PASSWORD`), so a missing value fails before
`initdb`.

Existing volumes do not run init scripts. Apply
`scripts/provision-service-db-roles.sh` once with the three passwords in the
environment, after a backup. From the repository root:

```powershell
# With the new .env values in place and application services stopped:
docker compose up -d --no-deps --wait --force-recreate postgres
Get-Content scripts/provision-service-db-roles.sh -Raw |
  docker compose exec -T postgres sh -s
```

Recreating the container gives `docker compose exec` the three role-password
variables from `.env`; on an existing volume the init scripts do not re-run.
The script uses the container's local superuser socket, so it needs no host
`psql` or password argument. If the container cannot be recreated yet, load the
three values into the shell and pass them with `-e`, accepting that they appear
in the host `docker` argv.

The script creates/updates the roles, ensures `vector` exists in `agenthub`,
changes database/public-schema ownership, reassigns existing tables, sequences,
enums, views, materialized views and functions, and revokes public connect. It
is not automatic and was not run against the main deployment.

## Rollout and rollback

1. Generate independent URL-safe `AUTH_DB_PASSWORD`, `WEBHOOK_DB_PASSWORD`,
   `AGENT_DB_PASSWORD`, `REDIS_PASSWORD`; put them in `.env`.
2. For an existing volume: stop application services, back up PostgreSQL,
   run the provisioning script, verify each role can connect only to its own
   database and migrate, then restart with the new Compose.
3. Fresh volume: just start PostgreSQL first and let `01`/`02` run.
4. Redis data persists across `requirepass`; the service URLs must carry the
   same password on restart. Recreate `redis` as well as the app services
   (plain `docker compose up -d`, or include `redis` in the restart list);
   otherwise new app containers authenticate against the old passwordless
   Redis container.
5. Rollback means restoring the previous `.env`/Compose and restarting; roles
   can remain. No table data is deleted by this change. Do not roll back by
   dropping roles or databases.

## Verification

- `tests/test_verify_infra_auth.py` checks the required blank secrets, Redis
  auth wiring, scoped `DATABASE_URL`s, the `postgres` role-password environment,
  and `REVOKE CONNECT` in both provisioning scripts.
- Static checks performed at implementation time: PyYAML parse of
  `docker-compose.yml`, `bash -n` on both shell scripts, the NexusCore unittest
  suite and ruff on the new test.
- Dynamic PostgreSQL/Redis acceptance was completed on 2026-10-30 against
  disposable containers; see
  `docs/security-hardening-stage-c-dynamic-2026-10-30.md`. Roles are created on a
  fresh volume, each role can create/write only in its own database, cross-database
  `CONNECT` fails for both other service roles and for an unrelated LOGIN role,
  Alembic `upgrade head` succeeds as each role, and Redis returns `NOAUTH` without
  the password and `PONG` with `REDISCLI_AUTH`.

## Residuals

- Per-service Redis ACLs and network segmentation are not included.
- Existing-volume role reassignment is a reviewed manual operation, not an
  automatic migration. A failed fresh init leaves an initialized data directory;
  on a disposable empty volume only, remove it with `docker compose down -v`
  before retrying. Never do that against existing data.
- Superuser credentials remain in the `postgres` service environment for
  initialization and healthchecks; role passwords are also visible in service
  environment/`docker inspect` and in `psql` argument lists during manual
  provisioning. Use a root-only secrets file for stronger handling.
- Service roles can connect to the `postgres` maintenance database (no tenant
  data) and own their whole application database, so they can create/drop
  objects inside it. Cross-application database access is denied.
- `vector` must exist in `agenthub` before an AgentHub migration runs; fresh
  `01` and the provisioning script create it as superuser.
