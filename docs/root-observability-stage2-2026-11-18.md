# Root observability Stage 2 acceptance — 2026-11-18

Status: **partial**. The `observability-logs` profile builds and runs, and the
durability, health and retention checks pass. The relay-dependent checks remain
**Blocked** on a synthetic bot/AI job and a fresh owner JWT.

## Environment

- PipeWatch `master` at `ff44a10` (PR #2), with the platform-mode path and the
  durable Redis/ClickHouse pipeline.
- PipeWatch image was built directly with `docker build`; Compose bake fails on
  this host.
- The profile ran in project `nexuscore` with `--no-deps`, so the base stack was
  not recreated or stopped.
- A temporary subnet override (`10.255.253.0/24`) avoided the exhausted Docker
  address pools; it is not committed.
- A temporary env file supplied a synthetic `PIPEWATCH_CLICKHOUSE_PASSWORD`;
  the repository `.env` was not modified.

## Evidence

| Check | Result |
| --- | --- |
| `pipewatch_clickhouse`, `pipewatch_redis`, `pipewatch` | healthy |
| `GET /health` | `{"status":"ok"}` |
| `GET /ready` | `{"status":"ready"}` |
| `GET /metrics` | `404` (tenant/platform metrics are not exposed) |
| Redis `appendonly` / `appendfsync` / `maxmemory-policy` | `yes` / `always` / `noeviction` |
| ClickHouse `pipewatch.logs` TTL | `toIntervalDay(30)` (ClickHouse's normalized form of the 30-day contract) |
| Base stack containers, volumes and data | untouched |
| PipeWatch containers after the run | stopped; volumes retained |
| Disposable test Redis/ClickHouse and the logs network | removed |

## Blocked checks

- Relay sweep against EventPipe ingest/query and PipeWatch with all three
  existing event types and equal envelopes.
- Repeated relay run with the same state: no new accepted records and no new
  rows.
- Tenant B denial on both sinks.
- EventPipe outage: `unknown` on EventPipe, `accepted` on PipeWatch, no
  automatic resend.
- PipeWatch backlog: `429` at capacity and drain after ClickHouse recovery.
- Alert cooldown: exactly one event per rule/window, no Telegram call.

These require a registered bot, at least one stored AI job, and a short-lived
owner JWT. Creating them writes to the running root services, so it was not
done without explicit approval. The relay also remains a host CLI by design.

## Reproduction notes

- The profile requires the PipeWatch revision with `PLATFORM_AUTH_ENABLED` and
  `AUTHFORTRESS_URL`; `master` at `ff44a10` provides it.
- ClickHouse stores the TTL as `toIntervalDay(30)`; a `grep "INTERVAL 30 DAY"`
  on `system.tables` will miss it.
