# Root observability Stage 1 acceptance — 2026-11-16

Status: **partial**. The profile builds and runs, the migration reaches
`002_tenant_boundary`, and the safe checks pass. The authorized tenant
round-trip, tenant B denial, Kafka-stop 503 and DLQ count remain **Blocked** on
a short-lived owner JWT with membership in two tenants.

## Environment

- NexusCore worktree on the observability branch; EventPipe `main` at
  `e450478` (platform mode, `alembic.ini`, `migrations/001`, `002`).
- Images were built with direct `docker build` because `docker compose build`
  fails on this host with `failed to execute bake: exit status 1`.
- The profile ran in project `nexuscore` with `--no-deps` so the running base
  stack was not recreated or stopped.
- A temporary subnet override (`10.255.254.0/24`) was required because the
  Docker address pools are exhausted by retained fixtures. The override is not
  committed.
- A temporary env file supplied synthetic `EVENTPIPE_*` and `SEAWEEDFS_*`
  values; the repository `.env` was not modified.

## Evidence

| Check | Result |
| --- | --- |
| `eventpipe_postgres`, `zookeeper`, `kafka`, `seaweedfs` | healthy |
| `eventpipe_migrate` | `alembic_version` = `002_tenant_boundary` |
| `eventpipe_ingest`, `eventpipe_transform`, `eventpipe_query` | healthy |
| ingest and query `/health` | `{"status":"ok"}` |
| transform `:9101/health` | `OK` |
| `/metrics` labels | no `tenant_id`, `bot_id`, `event_id`, `trace_id` |
| `POST /api/v1/events` without bearer | `401` |
| Base stack containers, volumes and data | untouched |
| EventPipe containers after the run | stopped; volumes retained |

## Blocked checks

- Authorized `POST /api/v1/events` with an owner bearer and `X-Tenant-ID`.
- Tenant A sees its event; tenant B is denied or sees an empty list.
- `docker compose stop kafka` then an authorized POST returns `503`.
- Malformed record reaches `events.dlq`; `dlq_count` increases.

These require a short-lived owner JWT that is a member of two tenants. Creating
that user/tenant would write to the running AuthFortress database, so it was not
done without explicit approval.

## Reproduction notes

- Build images directly, then tag them with the project prefix before `up`:
  `docker tag observability-events-eventpipe_transform nexuscore-eventpipe_migrate`.
- Zookeeper healthcheck must be `cub zk-ready localhost 2181`; the trailing
  timeout argument is rejected by the image.
