# Root observability Stage 1 acceptance — 2026-11-16/17

Status: **complete for the documented Stage 1 checks** using a disposable
AuthFortress issuer. The running root AuthFortress database was not modified.

## Environment

- NexusCore worktree on the observability branch; EventPipe `main` at
  `e450478` (platform mode, `alembic.ini`, `migrations/001`, `002`).
- Images were built with direct `docker build` because `docker compose build`
  fails on this host with `failed to execute bake: exit status 1`. The images
  were tagged with the `nexuscore-` project prefix before `up`.
- A disposable AuthFortress (`sha256:65256c…`), PostgreSQL and Redis ran on the
  project networks with their own database. EventPipe `EVENTPIPE_AUTH_URL` and
  `QUERY_AUTH_URL` were overridden to that issuer through a temporary compose
  override. No live root AuthFortress user or tenant was created.
- A temporary subnet override (`10.255.254.0/24`) was required because the
  Docker address pools are exhausted by retained fixtures. Neither override is
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
| Authorized `POST` as tenant A owner | `200`, storage event id returned |
| Same body posted twice | `200` twice, two storage events (known non-gate) |
| `POST` as A with tenant B selector | `404` |
| `GET /api/v1/events` as A for tenant A | `200`, one safe event (`event_id`, `event_type`, `payload_preview`, `processed_at`, `source`) |
| `GET` as A with tenant B selector | `404` |
| Kafka stopped, authorized `POST` | `503` `event broker unavailable`, not a false 200 |
| Malformed record to `events.raw` | one sanitized DLQ record (topic, partition, offset, tenant_id, error class, sha256; no raw input) |
| Base stack containers, volumes and data | untouched |
| EventPipe containers after the run | stopped; volumes retained |
| Disposable AuthFortress/PostgreSQL/Redis | removed |

## Known non-gate

Posting the same body twice creates two storage events because EventPipe
generates its own storage ID. The Stage 3 gate is one row per
`(tenant_id, envelope.event_id)`; recorded here as a duplicate count, not as
idempotency.

## Reproduction notes

- Build images directly, then tag them with the project prefix before `up`:
  `docker tag observability-events-eventpipe_transform nexuscore-eventpipe_migrate`.
- Zookeeper healthcheck must be `cub zk-ready localhost 2181`; the trailing
  timeout argument is rejected by the image.
- Authorized ingest needs an owner bearer and `X-Tenant-ID`; foreign tenants get
  `404`.
