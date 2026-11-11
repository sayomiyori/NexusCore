# Root observability integration: EventPipe and PipeWatch

Status: proposal for review, 2026-11-11. Documentation only: no code, migration,
Compose or runtime change is part of this file.

Base: `origin/main` at `5cd31467386c5ff5e234fc12e4b7a0818f289c88`.

## Status vocabulary

- **Implemented** — the behaviour exists in a repository and has recorded
  isolated acceptance. It is not automatically active in the root stack.
- **Planned** — agreed design, no implementation in the target repository yet.
- **Blocked** — cannot be completed without a missing credential, contract or
  decision. Do not present a blocked item as ready.

Summary:

- Add EventPipe and PipeWatch to the root Compose as two opt-in profiles, with
  dedicated PostgreSQL/Redis/Kafka/ClickHouse/SeaweedFS instances.
- Keep the existing relay as an operator-owned host CLI in Stage 2; do not put a
  human JWT or a DNS-name transport into Compose.
- Treat the logical envelope and tenant scope as contracts; record that
  consumer-side idempotency is still missing.
- Roll out in three stages: EventPipe, then PipeWatch plus relay, then hardening.
  The third stage contains blocked items and is not part of the first release.

## 1. Current baseline

| Area | State | Evidence |
| --- | --- | --- |
| EventPipe platform mode, Kafka/PG/S3 pipeline, DLQ, tenant query API | **Implemented** in the sibling repository; standalone deployment | [EventPipe repository](https://github.com/sayomiyori/EventPipe), `README.md` and `specs/local-hardening.md` there |
| PipeWatch platform mode, Redis-backed ingest, ClickHouse, alerts | **Implemented** in the sibling repository; standalone deployment | [PipeWatch repository](https://github.com/sayomiyori/PipeWatch), `README.md` and `specs/local-hardening.md` there |
| Root metadata relay (`scripts/relay_observability.py`) | **Implemented**, opt-in operator CLI, isolated acceptance only | [observability-flow.md](observability-flow.md), [docs/observability-flow.md](../docs/observability-flow.md) |
| Root Compose with EventPipe/PipeWatch | **Not implemented**. The root starts AuthFortress, WebHook Manager, AgentHub, PostgreSQL and Redis only | [docker-compose.yml](../docker-compose.yml), [README.md](../README.md) |
| Dashboard Overview/Events reads EventPipe/PipeWatch | **Implemented** as a separate read-only package; not this change | [dashboard-overview.md](dashboard-overview.md), [dashboard-events.md](dashboard-events.md) |
| Consumer-side idempotency in EventPipe/PipeWatch | **Not implemented** | See §3.5 |
| Machine-to-machine tenant credential for the relay | **Blocked** | See §10 |
| Root activation of EventPipe/PipeWatch/relay | **Planned** | This document |

The root Compose file does not start EventPipe or PipeWatch, and the relay itself is
not a root service. Any statement that the root already has an event/log pipeline
would be false.

## 2. Scope and boundaries

### 2.1 What is added to the root Compose

The root Compose becomes the runtime host for the existing service images. It does
not take ownership of their code, schemas or tests. Build contexts follow the
existing sibling layout: `../EventPipe` and `../PipeWatch` must be cloned next to
`NexusCore`, just like `../AuthFortress`, `../WebHook_Manager` and `../AgentHub`.

Two opt-in profiles are added. They are never enabled by default and never become
dependencies of the current AuthFortress/WebHook/AgentHub startup.

| Profile | Services | Purpose |
| --- | --- | --- |
| `observability-events` | `zookeeper`, `kafka`, `kafka_init`, `eventpipe_postgres`, `seaweedfs`, `seaweedfs_init`, `eventpipe_migrate`, `eventpipe_ingest`, `eventpipe_transform`, `eventpipe_query` | Tenant-scoped event path: REST/gRPC ingest to Kafka, transform to PostgreSQL/S3, query API |
| `observability-logs` | `pipewatch_clickhouse`, `pipewatch_redis`, `pipewatch` | Tenant-scoped log-record path: durable Redis admission, ClickHouse storage, query/alert API |

Service contract for the root profiles:

| Service | Internal endpoint | Published on host | Restart |
| --- | --- | --- | --- |
| `eventpipe_ingest` | `eventpipe_ingest:8013`, gRPC `:50051` | `127.0.0.1:28013` HTTP only | `unless-stopped` |
| `eventpipe_query` | `eventpipe_query:8020` | `127.0.0.1:28020` | `unless-stopped` |
| `eventpipe_transform` | health `:9101` | not published | `unless-stopped` |
| `eventpipe_postgres` | `:5432` | not published | `unless-stopped` |
| `kafka` | `:9092` | not published | `unless-stopped` |
| `zookeeper` | `:2181` | not published | `unless-stopped` |
| `seaweedfs` | S3 `:8333`, master `:9333` | not published | `unless-stopped` |
| `pipewatch` | `:8000` | `127.0.0.1:28084` | `unless-stopped` |
| `pipewatch_clickhouse` | `:8123`, `:9000` | not published | `unless-stopped` |
| `pipewatch_redis` | `:6379` | not published | `unless-stopped` |
| `eventpipe_migrate` | one-shot Alembic job | not published | `no` |
| `kafka_init`, `seaweedfs_init` | one-shot topic/bucket setup | not published | `no` |

The published ports use the `28xxx` range to avoid the existing
`8001`, `8014`, `28080`, `25432` and `26379` root ports and the default sibling
ports `18080`, `18123`, `16379`, `8013`, `8020`, `9092`, `8333`. All bind to
`127.0.0.1`.

Kafka follows the tested EventPipe layout: `events.raw` with 3 partitions and
`events.dlq` with 1 partition, replication factor 1, created by `kafka_init`.
This is a local single-broker demo, not an HA topology.

### 2.2 What stays standalone

- The sibling `EventPipe/docker-compose.yml` and `PipeWatch/docker-compose.yml`
  remain the supported standalone development environments. Root profiles do not
  replace or edit them.
- **The relay stays an operator-owned host CLI in Stage 2.** It is not
  containerised in this specification. It connects to the root through the
  published loopback ports. Containerising it is a Stage 3 item because the
  current origin validator accepts only numeric IPv4 origins, not Compose DNS
  names (see §10).
- EventPipe/PipeWatch Prometheus and Grafana services remain in their sibling
  Compose files. The root does not add Prometheus, Grafana or Alertmanager.
- The dashboard stays a separate Next.js package. It reads the same tenant-scoped
  APIs and is not changed here.
- AuthFortress, WebHook Manager and AgentHub keep their current code and output
  contracts. No new producer is embedded into them.
- Raw container stdout/stderr collection is not added. See §10.

### 2.3 Infrastructure isolation decision

The root PostgreSQL and Redis are **not reused** for EventPipe or PipeWatch.

- The root Redis has no AOF/`appendfsync always`/`noeviction` contract and is
  shared by AuthFortress (db 1), WebHook (db 2) and AgentHub (db 3). PipeWatch
  requires a durable queue with `appendonly=yes`, `appendfsync=always`,
  `maxmemory-policy=noeviction`, and losing that state loses accepted logs.
- The root PostgreSQL owns the AuthFortress, WebHook and AgentHub schemas and
  their migration histories. EventPipe needs its own Alembic history and its own
  tenant-scoped event tables; adding a database to an existing volume depends on
  first-volume initialization and is not a safe migration path.
- EventPipe raw events require an S3-compatible store. SeaweedFS is added for
  that purpose; the root has no S3 service.
- Kafka and ClickHouse are dedicated to these profiles. They are not published
  and are not shared with any existing root service.

This keeps the existing data, volumes, keyspaces and migration ownership
untouched. The cost is more containers; that is accepted for a local demo.

### 2.4 Network layout

- `nexus_net` remains the existing application network.
- `observability_events_net` is an internal network for Kafka, ZooKeeper,
  EventPipe PostgreSQL, SeaweedFS, transform and query. Ingest and query also
  join `nexus_net` because they call AuthFortress. Transform has no external
  egress.
- `observability_logs_net` is an internal network for PipeWatch, ClickHouse and
  its Redis. PipeWatch also joins `nexus_net` for AuthFortress.
- `internal: true` is used where the service does not need internet egress. The
  relay runs on the host and reaches only the published loopback ports.

### 2.5 Named volumes

New named volumes, never reused from the base stack:

- `nexus_eventpipe_postgres_data`
- `nexus_eventpipe_seaweed_data`
- `nexus_kafka_data`
- `nexus_pipewatch_clickhouse_data`
- `nexus_pipewatch_redis_data`
- `nexus_relay_state` — only if the relay is later containerised; Stage 2 keeps
  its SQLite file under the operator's chosen host path.

No acceptance step deletes these volumes. A failed run is stopped and retained
for inspection, following the existing repository practice.

### 2.6 Configuration contract

`.env.example` entries and placeholders, values supplied only by the operator:

| Variable | Used by | Rule |
| --- | --- | --- |
| `EVENTPIPE_DB_PASSWORD` | `eventpipe_postgres`, EventPipe services | Required for the events profile; URL-safe; never printed |
| `SEAWEEDFS_ACCESS_KEY`, `SEAWEEDFS_SECRET_KEY` | SeaweedFS and EventPipe S3 clients | Required; internal-only credentials; not the root PostgreSQL/Redis passwords |
| `PIPEWATCH_CLICKHOUSE_PASSWORD` | `pipewatch_clickhouse`, `pipewatch` | Required for the logs profile; never printed |
| `NEXUS_EVENTS_TOKEN` | Host relay | Existing placeholder; short-lived owner JWT; process environment only |
| `PLATFORM_READ_ENABLED` | AgentHub AI source | Existing flag; `true` only for the Stage 2 synthetic acceptance, otherwise keep the current value |
| `PLATFORM_BOTS_ENABLED` | WebHook bot source | Existing flag; `true` only for the Stage 2 synthetic acceptance, otherwise keep the current value |

Current PipeWatch has no Redis password setting, so do not add
`PIPEWATCH_REDIS_PASSWORD` to `.env.example`; keep `pipewatch_redis` internal-only
and unpublished until the sibling supports authentication.

The Compose profiles set `EVENTPIPE_PLATFORM_MODE=true`,
`QUERY_PLATFORM_MODE=true`, `TRANSFORM_PLATFORM_MODE=true`,
`PLATFORM_AUTH_ENABLED=true`, `METRICS_ENABLED=false` and
`TELEGRAM_NOTIFICATIONS_ENABLED=false` as literals. They must not be silently
overridable to a standalone mode in the root.

## 3. Event contract

### 3.1 Envelope

The logical envelope is the same for both sinks and for every event type. The
channel-specific wrapping is defined in §3.4; the envelope itself is not changed
by the receiver.

| Field | Type | Required | Rule |
| --- | --- | --- | --- |
| `event_id` | UUID string | yes | Deterministic UUIDv5, canonical lowercase. Stable for one logical observation version; a changed state is a new event. |
| `event_type` | string | yes | Allowlisted dot-separated type, max 128 ASCII characters. No caller-defined free-form types. |
| `schema_version` | integer | yes | `1` for this contract. Additive changes keep `1`; breaking changes require a new major and a dual-read window. |
| `occurred_at` | RFC 3339 string | yes | Timezone-aware UTC, normalized to `+00:00`. Naive timestamps are rejected. This is source event time, not ingestion time. |
| `tenant_id` | UUID string | yes | Canonical tenant from AuthFortress. Never taken from the request body alone. |
| `bot_id` | UUID string or `null` | yes | Required for bot/job events; `null` only for tenant-level events. Empty string is invalid. |
| `correlation_id` | UUID string | yes | Upstream reference: ingress event UUID for AI jobs, tenant UUID for tenant snapshots, bot UUID for bot snapshots. It is not unique and is not an idempotency key. |
| `payload` | JSON object | yes | Allowlisted per event type, max 16 KiB canonical JSON, no free-form text. |

The existing relay also emits `idempotency_key` with the same value as `event_id`.
It is a derived compatibility field, not a separate identity. Consumers must use
`event_id`.

Example:

```json
{
  "event_id": "6f1c2d9e-4a7b-5c8d-9e0f-1a2b3c4d5e6f",
  "event_type": "ai.job.observed",
  "schema_version": 1,
  "occurred_at": "2026-11-11T09:15:00+00:00",
  "tenant_id": "00000000-0000-4000-8000-000000000001",
  "bot_id": "00000000-0000-4000-8000-000000000002",
  "correlation_id": "00000000-0000-4000-8000-000000000003",
  "payload": {
    "job_id": "00000000-0000-4000-8000-000000000004",
    "ingress_event_id": "00000000-0000-4000-8000-000000000003",
    "state": "completed",
    "attempts": 1
  }
}
```

### 3.2 Event types and payload allowlist

Only these types are in scope. A new type requires a separate contract and a new
`event_type` entry; it is not accepted by a generic endpoint by accident.

| `event_type` | Source | `bot_id` | Allowlisted `payload` keys | Severity mapping |
| --- | --- | --- | --- | --- |
| `ai.job.observed` | AgentHub tenant-authorized job metadata | required | `job_id`, `ingress_event_id`, `state`, `attempts` | `error` for `failed`/`unknown`; otherwise `info` |
| `auth.tenant.observed` | AuthFortress tenant read | `null` | `tenant_created_at`, `observed_role` | `info` |
| `webhook.bot.observed` | WebHook bot registry read | required | `is_active`, `webhook_status` | `error` for `failed`/`unknown`; otherwise `info` |

Explicitly forbidden in `payload`: tenant or bot names, Telegram user/chat
identifiers, tokens, cookies, message text, answers, prompts, provider/model
names, request bodies, free-form exception text, IP addresses, email addresses.
`auth.tenant.observed` is a tenant-access snapshot, not a login/logout audit.

`occurred_at` semantics:

- `ai.job.observed` — the job's `updated_at` from AgentHub.
- `webhook.bot.observed` — the bot's `updated_at` from WebHook.
- `auth.tenant.observed` — the first local observation time. The tenant creation
  time stays in `payload.tenant_created_at`; it is not used as event time.

### 3.3 Identity and deterministic event ID

`event_id` is a UUIDv5 over a canonical JSON tuple. The exact tuple is implemented
in [`scripts/relay_observability.py`](../scripts/relay_observability.py) and must
not change without a schema version bump. The important properties are:

- the same tenant, bot, source object and source state produce the same
  `event_id` on every replay;
- a changed state, attempt count or source timestamp produces a new `event_id`;
- polling time is never part of identity for job/bot events;
- the tenant is part of identity; the same object in another tenant cannot
  collide.

The relay stores `(event_id, sink)` as a primary key in SQLite and claims a
pending row before the HTTP call. This is producer-side idempotency: a repeated
relay sweep cannot send an accepted delivery twice. It is not consumer-side
idempotency.

### 3.4 Transport mapping

EventPipe receives the envelope as the `payload` of its existing event API and
keeps the relay identity in scalar metadata:

```json
{
  "source": "nexuscore",
  "event_type": "ai.job.observed",
  "payload": {
    "event_id": "6f1c2d9e-4a7b-5c8d-9e0f-1a2b3c4d5e6f",
    "event_type": "ai.job.observed",
    "schema_version": 1,
    "occurred_at": "2026-11-11T09:15:00+00:00",
    "tenant_id": "00000000-0000-4000-8000-000000000001",
    "bot_id": "00000000-0000-4000-8000-000000000002",
    "correlation_id": "00000000-0000-4000-8000-000000000003",
    "payload": {
      "job_id": "00000000-0000-4000-8000-000000000004",
      "ingress_event_id": "00000000-0000-4000-8000-000000000003",
      "state": "completed",
      "attempts": 1
    }
  },
  "metadata": {
    "relay_event_id": "6f1c2d9e-4a7b-5c8d-9e0f-1a2b3c4d5e6f",
    "bot_id": "00000000-0000-4000-8000-000000000002"
  }
}
```

The EventPipe response `event_id` is the receiver's storage UUID. It is **not**
the envelope `event_id`; do not use it as the logical identity. Query the detail
endpoint and read `payload.event_id` or `metadata.relay_event_id`.

PipeWatch receives the same envelope as `metadata`, with fixed service/message
and the envelope ID as `trace_id`:

```json
{
  "service": "nexuscore",
  "level": "info",
  "message": "ai.job.observed",
  "trace_id": "6f1c2d9e-4a7b-5c8d-9e0f-1a2b3c4d5e6f",
  "metadata": {
    "event_id": "6f1c2d9e-4a7b-5c8d-9e0f-1a2b3c4d5e6f",
    "event_type": "ai.job.observed",
    "schema_version": 1,
    "occurred_at": "2026-11-11T09:15:00+00:00",
    "tenant_id": "00000000-0000-4000-8000-000000000001",
    "bot_id": "00000000-0000-4000-8000-000000000002",
    "correlation_id": "00000000-0000-4000-8000-000000000003",
    "payload": {
      "job_id": "00000000-0000-4000-8000-000000000004",
      "ingress_event_id": "00000000-0000-4000-8000-000000000003",
      "state": "completed",
      "attempts": 1
    }
  }
}
```

PipeWatch stores its own random `log_id`. The logical ID is `trace_id` or
`metadata.event_id`. Its row timestamp is ingestion time; `occurred_at` remains
inside metadata.

### 3.5 Consumer idempotency

The required target behaviour is:

- the consumer persists a unique key `(tenant_id, event_id)`;
- a duplicate delivery returns the same success status as the first delivery
  (200/202, never 409) and creates no second row, notification, usage record or
  alert;
- a duplicate must not be reported as a conflict when the complete envelope is
  byte-equivalent; different content under the same `(tenant_id, event_id)` is a
  conflict and fails closed.

Current state, explicitly **not** compliant:

| Receiver | Current identity | Duplicate POST effect | Status |
| --- | --- | --- | --- |
| EventPipe | Ingest generates a new storage UUID per request (`producer.new_event_id()`); `processed_events.event_id` is unique only on that generated value | Two rows, two S3 objects | **Not implemented** |
| PipeWatch | `LogEntryCreate.to_record()` generates `uuid4()` per request; ClickHouse is `MergeTree` with no unique constraint | Two rows | **Not implemented** |
| Relay | SQLite `relay_deliveries(event_id, sink)` primary key; accepted/unknown rows are never resent | Normal relay repeat adds no row | **Implemented** (producer-side only) |

Until the receiver gap is closed, the following rules apply:

- normal relay repeats are safe; manual re-POSTs and ambiguous ClickHouse writes
  can duplicate rows;
- analytics must use `COUNT(DISTINCT payload.event_id)` (EventPipe) or
  `COUNT(DISTINCT trace_id)` (PipeWatch), never raw row counts;
- the dashboard already merges observations by relay UUID and flags conflicting
  content; keep that behaviour;
- no exactly-once claim is allowed anywhere in the root runbook.

Closing this gap is a Stage 3 gate. It requires sibling-repository changes and
separate acceptance; this document does not authorize them.

### 3.6 Validation and size limits

- Event body: at most 16 KiB canonical JSON for the envelope; the transport body
  limit remains EventPipe 1 MiB and PipeWatch 1 MiB.
- EventPipe `metadata` is `dict[str, str]`; do not put nested objects there.
  The envelope with its nested payload belongs in `payload`.
- `event_type` unknown to the allowlist: reject with 422 at the producer edge or
  send to DLQ at transform; never store as a supported observation. Current
  EventPipe does not enforce this allowlist itself; the relay is the only producer
  in this scope and sends only the three types. Receiver-side enforcement is a
  Stage 3 hardening item.
- `tenant_id` mismatch between the authenticated context and the envelope:
  reject; do not silently rewrite. Receiver-side enforcement is a Stage 3 item
  because current EventPipe treats `payload` as opaque.
- `bot_id` that does not belong to the tenant: reject at the source read; the
  relay already fails closed on canonical bot mismatch.
- Non-finite numbers, duplicate JSON keys, control characters and non-ASCII
  `event_type` are rejected by the relay's strict parser. Keep those checks.

## 4. Tenant scoping and isolation

### 4.1 Authority chain

1. The relay/operator supplies a short-lived owner JWT in
   `NEXUS_EVENTS_TOKEN`; the token is never a CLI argument, a URL, a log line or
   SQLite state.
2. Every source read and every sink write sends `Authorization: Bearer ...` and
   `X-Tenant-ID: <canonical UUID>`.
3. EventPipe/PipeWatch call AuthFortress
   `POST /api/v1/tenants/{tenant_id}/authorize` on every request. The tenant ID
   in the header is only a selector; the canonical context comes from the
   issuer response. There is no positive authorization cache.
4. Missing/invalid credential: 401. Invisible/foreign tenant: 404. Member
   write: 403. Identity outage or malformed response: 503.
5. The relay binds its SQLite state to tenant, bot and all selected origins.
   Opening that state with another tenant/bot/origin set fails closed.

`payload.tenant_id` is advisory data for downstream analytics. It is **never**
the authorization source. A consumer that reads it must compare it with the
outer authorized tenant and reject a mismatch.

### 4.2 Storage scoping

| Layer | Tenant control |
| --- | --- |
| EventPipe Kafka envelope | Server-derived `tenant_id` written by ingest; transform rejects a missing tenant in platform mode |
| EventPipe PostgreSQL | `processed_events.tenant_id` indexed; every list/detail/stats query filters it |
| EventPipe S3 | Raw object key is `tenants/{tenant_id}/...`; platform raw reads proxy bytes only after the same tenant-scoped row lookup |
| EventPipe DLQ/failures | `failed_events.tenant_id`; sanitized diagnostics; per-tenant counts |
| PipeWatch ClickHouse | `tenant_id` column; every query, count, aggregate, stats and service list filters it |
| PipeWatch Redis | The shared queue/processing records carry the server-selected tenant; streams, rules, cooldown and history keys include the tenant; platform mode cannot read the empty standalone scope |
| PipeWatch WebSocket | Authorization before accept and reauthorization on every read cycle; credentials never in URL parameters |
| Relay | One tenant/bot per state file; no shared state across tenants |

### 4.3 Metrics, logs and analytics

- **No tenant identifiers in Prometheus labels.** Do not add `tenant_id`,
  `bot_id`, `event_id`, `trace_id` or user-selected source/type as label values.
  They are unbounded and leak tenant topology.
- PipeWatch `/metrics` returns 404 in platform mode. `METRICS_ENABLED=false` is
  set explicitly in the root profile. EventPipe `/metrics` remains an
  operational, loopback-only endpoint; it is not a tenant analytics API.
- Application logs contain static diagnostics and at most a canonical UUID when
  correlation is necessary. No tenant names, Telegram identities, message text,
  payloads, JWTs, passwords or provider keys.
- Analytics and dashboards read only tenant-scoped query APIs. There is no
  global aggregate endpoint in platform mode. `/api/v1/stats` on both services
  is scoped to the authenticated tenant.
- Alert rules, cooldown keys and alert history are per tenant. A shared cooldown
  across tenants would suppress one tenant's alert because another tenant fired.
- The dashboard BFF must continue to reject a foreign tenant before calling any
  sink and must not cache one tenant's response for another.

### 4.4 Negative isolation gates

These are mandatory for any stage that claims tenant safety:

- tenant B cannot read tenant A's event by storage UUID: EventPipe detail and
  raw return 404;
- tenant B's list query returns an empty page, not A's rows and not A's total;
- tenant B cannot read A's PipeWatch logs by `trace_id`, service filter or
  full-text search;
- tenant B cannot create, update or delete A's alert rule: 404, not 403 with
  existence disclosure;
- a WebSocket opened with B's token never receives A's stream, including after
  token revocation;
- direct SQL/ClickHouse count with B's tenant filter returns zero for A's rows;
- a relay state file bound to A refuses to open for B before any HTTP call.

## 5. Backpressure, retry, dead letters and retention

### 5.1 Current behaviour

| Component | Admission and backpressure | Retry | Dead letter | Known gap |
| --- | --- | --- | --- | --- |
| Relay | SQLite claim, one POST per delivery, no queue | None; `unknown` is never retried | None; manual reconciliation only | A definite 503/429 after the claim becomes `unknown`, not retryable |
| EventPipe ingest | Kafka `send_and_wait` with a 5 s timeout; Kafka failure returns 503; no local buffer | aiokafka internal only | n/a at ingest | Batch endpoint sends sequentially; a mid-batch failure can leave earlier events accepted |
| EventPipe transform | `getmany(max_records=20)` | 3 attempts total (`max_retries=3`), sleeps `0.5 s` and `1 s` between them | Kafka `events.dlq` for validation/permanent errors; sanitized `failed_events` row | Infrastructure failure escapes and the offset stays uncommitted, so the same event replays until the dependency recovers |
| EventPipe query | PostgreSQL read; no write path | None | n/a | Query outage makes the dashboard mark that receiver unavailable |
| PipeWatch app | Atomic Redis backlog admission, `APP_QUEUE_MAXSIZE=20000`; full backlog returns 429; `APP_BATCH_SIZE=1000`; flush every 1 s; 30 s lease renewed every 5 s | ClickHouse insert failure retries every flush interval, indefinitely | None | A poison batch stays in the processing list and blocks new claims; the backlog then fills and returns 429 |
| PipeWatch alerts | 30 s evaluation, 300 s default cooldown, 100 rules per tenant | One notification attempt; no retry | None | No global or per-tenant notification rate cap; many rules can fire together |

### 5.2 Target relay state machine

Current states are `pending`, `unknown`, `accepted`. The target adds a definite
non-acceptance state and a terminal dead letter:

```text
pending -> in_flight -> accepted
                     -> unknown        (ambiguous; no automatic retry)
                     -> rejected       (definite 4xx/429/503; retry with backoff)
                     -> dead_letter    (attempt limit reached)
```

Rules:

- `in_flight` is committed before the HTTP call, as today. A crash leaves an
  ambiguous outcome, never a silent success.
- `accepted` only after a valid receipt. `unknown` only when the request may have
  been accepted (transport timeout, connection reset after send, unreadable
  response). `unknown` is never retried automatically.
- `rejected` only when the receiver returned a response that guarantees no
  acceptance: 400/401/403/404/422, 429, or a 503 that is defined as
  "not accepted" by the receiver contract. EventPipe's 503 on Kafka failure and
  PipeWatch's 429 on full backlog qualify. The relay must not treat a proxy 502
  or a timeout as `rejected`.
- Retry schedule for `rejected`: base 5 s, factor 2, cap 300 s, jitter ±20 %,
  maximum 8 attempts. Store `next_attempt_at`; a sweep sends only rows whose
  time has arrived. After the limit, `dead_letter` and a nonzero exit.
- `dead_letter` rows are listed by a read-only operator command, never replayed
  automatically. Replay is a separate, explicitly approved command.
- This state machine requires consumer idempotency before it can safely retry a
  request that might have been accepted. The `rejected` status is limited to
  responses that prove non-acceptance; otherwise the row stays `unknown`.

### 5.3 Target dead-letter handling

- EventPipe keeps `events.dlq` plus `failed_events`. Invalid data goes to DLQ
  with a static error class and record hash; raw input and exception text are not
  stored. DLQ replay is manual and out of this scope.
- PipeWatch needs a bounded quarantine: after 5 failed ClickHouse flushes for the
  same claimed batch, move the batch to a Redis dead-letter list with a 7-day
  bound and a static failure code, then continue with the next batch. Today a
  permanently failing batch blocks the pipeline; that is the gap this stage
  closes.
- The relay dead letter is a SQLite row with the event ID, sink, attempt count,
  last status class and timestamp. It never contains the JWT or raw response
  body.
- No automatic deletion of dead letters. Retention is an operator decision.

### 5.4 Retention

These values are **proposed policy**, not current behaviour. They require
approval before implementation because they delete data. Retention is measured
from ingestion/`processed_at`, not from `occurred_at`, so a late replay does not
extend an old event's life indefinitely.

| Data | Current | Proposed root value | Mechanism | Status |
| --- | --- | --- | --- | --- |
| Kafka `events.raw` | Broker default, not pinned | 168 h and 10 GiB per partition | Topic config in `kafka_init` | Planned |
| Kafka `events.dlq` | Broker default, not pinned | 336 h and 2 GiB per partition | Topic config; no auto replay | Planned |
| EventPipe `processed_events` | Unbounded | 30 days | Daily bounded delete by `processed_at` | Planned |
| EventPipe `failed_events` | Unbounded | 30 days | Daily bounded delete by `failed_at` | Planned |
| EventPipe raw S3 objects | Unbounded | 30 days | Prefix cleanup or S3 lifecycle; SeaweedFS lifecycle support must be verified | Planned |
| PipeWatch ClickHouse `logs` | 30 days, hardcoded TTL | Keep 30 days | `TTL toDateTime(timestamp) + INTERVAL 30 DAY` | Implemented |
| PipeWatch Redis backlog | Bounded by 20 000 records, no time TTL | Keep count bound | `APP_QUEUE_MAXSIZE` | Implemented |
| PipeWatch alert history | Latest 500 per tenant | Keep | Redis list/hash bound | Implemented |
| PipeWatch live streams | `maxlen=100_000` per stream | Keep | Redis `XADD MAXLEN` | Implemented |
| Relay SQLite | No automatic deletion | Manual archive after all deliveries are accepted, suggested 90 days | Operator procedure | Planned |
| Root container logs | 10 MiB × 3 files | Keep; not analytics | Compose `json-file` defaults | Implemented |

No cleanup command runs as part of this specification. Deletion requires a
separate approved task with a dry-run count first.

## 6. Failure scenarios

| Scenario | Current / expected behaviour | Data effect | Operator action |
| --- | --- | --- | --- |
| Kafka unavailable at EventPipe start | Ingest retries startup 10 times with exponential backoff (2 s base), then exits | No event accepted; nothing lost by the receiver | Fix Kafka, restart ingest; check transform lag after recovery |
| Kafka unavailable after start | `POST /api/v1/events` waits up to 5 s and returns 503 | No acceptance; producer must retry | Relay must classify 503 as `rejected` in the target state machine; today it becomes `unknown` after the claim |
| EventPipe PostgreSQL unavailable | Transform makes 3 attempts total (sleeps 0.5 s and 1 s between them), then exits with `transform infrastructure unavailable`; offset remains uncommitted | Event replays from Kafka after restart; no silent drop | Restore PG, let the consumer replay; watch for duplicate effects after an ambiguous commit |
| EventPipe S3 unavailable | Same as PostgreSQL: retry then exit, offset uncommitted | Raw object may be re-uploaded under the same key; storage is idempotent by key | Restore S3; verify object count and hash |
| ClickHouse unavailable after PipeWatch start | Ingest continues into the bounded Redis backlog; flush retries every second; `/ready` returns 503; backlog fills to 20 000 then 429 | Accepted records remain in Redis until flushed; ambiguous inserts can duplicate | Restore ClickHouse; wait for backlog drain; check duplicates by `trace_id` |
| ClickHouse unavailable at PipeWatch start | App lifespan fails at `ensure_tables`; container restarts | Redis backlog is preserved if the volume is intact | Restore ClickHouse; restart app; do not delete Redis |
| PipeWatch Redis unavailable | Ingest and ready return 503; no acceptance | No new loss; pending records depend on AOF/volume | Restore Redis; if the volume was lost, accepted-but-unflushed data is lost; state that plainly |
| Relay source authorization fails | No sink calls for that source; pending rows wait; exit 1 with static diagnostics | Events are not delivered; no partial cross-source drain | Renew the owner JWT; rerun; do not reset the state file |
| Relay sink returns 503/429 after claim | Current: row becomes `unknown`, no automatic retry, other sink can still succeed | Possible loss if the sink did not accept; possible duplicate if it did | Run `--reconcile` against the EventPipe query API; inspect PipeWatch by `trace_id`; decide manually |
| Duplicate delivery | Relay repeat is deduplicated by SQLite; direct POST or ambiguous ClickHouse write can create a second row | Duplicate rows; no duplicate notification unless an alert is re-evaluated | Deduplicate reads by `event_id`/`trace_id`; close the consumer idempotency gap in Stage 3 |
| Loss | Kafka retention expiry, Redis volume loss, relay `unknown` without retry | Event absent from one or both sinks | No automatic recovery; record the gap; do not claim exactly-once |
| Alert storm | Many rules/tenants breach thresholds; only per-rule cooldown applies; no global cap | Notification flood; ClickHouse query load | Target per-tenant/global caps; today disable notifications in the root profile |
| Clock skew | `occurred_at` can be earlier/later than ingestion; no ordering guarantee | Query windows by ingestion time still work; event-time analytics can be skewed | Keep hosts on NTP; use `processed_at` for retention and operational windows |

### 6.1 The most dangerous current gap: 503 after claim

The relay commits `unknown` before it sends the HTTP request. If EventPipe returns
503 because Kafka is down, the event was **not** accepted, but the relay cannot
retry it automatically. Reconciliation will report `unresolved`, not `confirmed`.
This is a real potential loss window, not a theoretical one. The target
`rejected` state fixes it, but only after the receiver contract distinguishes
"not accepted" from "unknown" and the relay has tests for both. Until then,
operators must treat a sink outage during a relay sweep as a manual recovery
event.

### 6.2 PipeWatch poison batch

A ClickHouse batch that always fails stays in the `processing` list. `claim()`
returns the existing processing batch without popping new records, so the
pipeline stops advancing and the backlog fills. The app keeps accepting until
`APP_QUEUE_MAXSIZE`, then returns 429. There is no automatic discard. The Stage 2
runbook must tell the operator to inspect the failing batch and restore
ClickHouse; the Stage 3 quarantine is the actual fix.

### 6.3 Alert storm

PipeWatch evaluates every tenant scope and every rule every 30 seconds. Cooldown
is per rule (default 300 s), rules are capped at 100 per tenant, and each firing
makes at most one notification attempt. There is no per-tenant or global
notification budget, and a slow ClickHouse increases evaluation time. The root
profile keeps notifications disabled. The target is a per-tenant notification
budget of 10 per 10 minutes, a global budget of 60 per minute, a dedup key of
`(tenant_id, rule_id, window)`, and a suppressed counter without tenant labels.
A notification dropped by the budget must not be retried; the alert event remains
visible in history.

## 7. Stage plan

Three stages maximum. Each stage is separately approved, implemented, verified
and reported. A later stage does not start because an earlier stage "looks
fine"; it starts after the earlier acceptance evidence is recorded.

### Stage 1 — EventPipe in the root Compose (`observability-events`)

**Status: Planned for the root; EventPipe internals Implemented in the sibling
repository.**

Scope:

- add the EventPipe services, Kafka/ZooKeeper, dedicated PostgreSQL and SeaweedFS
  to the root Compose under the `observability-events` profile;
- set `EVENTPIPE_PLATFORM_MODE`, `QUERY_PLATFORM_MODE` and
  `TRANSFORM_PLATFORM_MODE` to `true`; point both auth URLs at
  `http://auth_service:8000`;
- pin Kafka retention, PostgreSQL/S3 volumes and healthchecks;
- run `eventpipe_migrate` as a one-shot job before the applications;
- keep the relay out of this stage; validate with a short-lived owner JWT and a
  synthetic event;
- update `.env.example` with placeholders only;
- do not change the sibling EventPipe repository.

Exit gate:

- `docker compose --profile observability-events config --quiet` passes;
- all services healthy, migration head is `002_tenant_boundary`;
- authorized POST/GET works; tenant B is denied;
- Kafka stop produces 503, not a false 200;
- a malformed event reaches the DLQ with a sanitized diagnostic;
- existing root containers, volumes and data are unchanged.

### Stage 2 — PipeWatch in the root Compose and first relay activation
(`observability-logs`)

**Status: Planned for the root; PipeWatch and relay internals Implemented in
isolated acceptance.**

Scope:

- add PipeWatch, ClickHouse and its dedicated Redis under `observability-logs`;
- set `PLATFORM_AUTH_ENABLED=true`, `AUTHFORTRESS_URL=http://auth_service:8000`,
  `METRICS_ENABLED=false`; keep Telegram notifications disabled;
- enforce Redis `appendonly=yes`, `appendfsync=always`,
  `maxmemory-policy=noeviction`;
- keep the existing ClickHouse 30-day TTL;
- run the existing host relay CLI against the published loopback ports:
  `28013` (EventPipe ingest), `28020` (EventPipe query for reconciliation) and
  `28084` (PipeWatch);
- require a fresh owner JWT; do not add a long-lived token to Compose;
- for the synthetic all-three-types acceptance, set `PLATFORM_READ_ENABLED=true`
  (AgentHub AI source) and `PLATFORM_BOTS_ENABLED=true` (WebHook bot registry).
  These are read/registry flags, not Telegram intake or live generation. The
  fixture needs one registered bot and at least one stored AI job; create them
  synthetically, do not run a provider. If either flag stays false, record that
  event type as not exercised, never as passed;
- no containerised relay, no DNS-name origin change, no sibling change.

Exit gate:

- `docker compose --profile observability-logs config --quiet` passes;
- PipeWatch `/health` and `/ready` return 200; Redis settings and ClickHouse TTL
  match the contract;
- all three existing event types arrive in both sinks with equal envelopes;
- a repeated relay run adds no accepted duplicates and no new rows;
- tenant B cannot read either sink;
- an EventPipe outage produces `unknown` on EventPipe and `accepted` on
  PipeWatch; no automatic resend;
- a full PipeWatch backlog returns 429 and drains after ClickHouse recovery
  within the configured bound;
- no real Telegram, LLM or provider call occurs; original root data is unchanged.

### Stage 3 — Unattended and correctness hardening

**Status: mixed; see the table.**

| Item | Status | Why |
| --- | --- | --- |
| Relay `rejected` state and bounded retry/backoff | **Planned** | Requires relay changes and tests; no sibling change |
| Consumer idempotency `(tenant_id, event_id)` in EventPipe and PipeWatch | **Blocked** | Needs sibling contracts, schema/API changes and separate acceptance |
| Machine-to-machine tenant credential for the relay | **Blocked** | AuthFortress currently authorizes only bearer JWTs for `tenant.manage`; no service principal exists |
| Containerised relay using Compose DNS names | **Blocked** | The relay's origin validator accepts only numeric IPv4; a bounded internal-host allowlist or a different transport decision is required |
| Retention cleanup jobs and dry-run evidence | **Planned** | Policy values in §5.4 need approval; deletion is a separate task |
| PipeWatch poison-batch quarantine and `Retry-After` | **Planned** | Sibling change; needs tests for 5-attempt quarantine and backlog drain |
| Per-tenant/global alert caps | **Planned** | Sibling change; needs a load test and a no-tenant-label metric |
| Raw application log shipping with tenant attribution | **Blocked / out of scope** | No producer contract exists; app logs do not carry a trustworthy tenant ID |

Stage 3 is not a single release. Each row needs its own design and evidence. Do
not call the root observability integration "production-ready" because Stage 1
and Stage 2 pass.

## 8. Acceptance criteria

Commands are PowerShell. Replace `<...>` placeholders through a secret manager or
the operator environment; never paste a real JWT into a command line, a file, a
commit or this document. `curl.exe` is used explicitly to avoid the PowerShell
`curl` alias.

### 8.1 Repository checks (available now)

At the time of writing, the documentation-only change is checked by:

```powershell
& D:\Programming\NexusCore\.venv\tooling-checks\Scripts\python.exe -m unittest discover -s tests -p "test_verify*.py" -q
& D:\Programming\NexusCore\.venv\tooling-checks\Scripts\python.exe -m ruff check --no-cache scripts tests
& D:\Programming\NexusCore\.venv\tooling-checks\Scripts\python.exe -m compileall -q scripts tests
```

Observed on this branch: **164 tests OK**, Ruff **All checks passed**. Record the
new exact count after any test change; do not copy 164 into later evidence.

### 8.2 Stage 1 — EventPipe root profile

```powershell
$env:EVENTPIPE_DB_PASSWORD = '<events database password>'
docker compose --profile observability-events config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Invalid observability-events Compose configuration' }

docker compose --profile observability-events up -d --wait --wait-timeout 300 `
  eventpipe_postgres zookeeper kafka seaweedfs
if ($LASTEXITCODE -ne 0) { throw 'EventPipe infrastructure did not become healthy' }

docker compose --profile observability-events run --rm eventpipe_migrate
if ($LASTEXITCODE -ne 0) { throw 'EventPipe migration failed' }

docker compose --profile observability-events up -d --wait --wait-timeout 300 `
  eventpipe_ingest eventpipe_transform eventpipe_query
if ($LASTEXITCODE -ne 0) { throw 'EventPipe applications did not become healthy' }

docker compose --profile observability-events ps
```

Expected health:

```powershell
curl.exe -fsS http://127.0.0.1:28013/health   # {"status":"ok"}
curl.exe -fsS http://127.0.0.1:28020/health   # {"status":"ok"}
docker compose exec eventpipe_transform python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9101/health', timeout=2).read().decode())"
# OK
curl.exe -fsS http://127.0.0.1:28013/metrics | Select-String "tenant_id|bot_id|event_id|trace_id"
# No output: operational metrics must not carry tenant/event labels.
```

Migration head:

```powershell
docker compose exec -e PGPASSWORD="$env:EVENTPIPE_DB_PASSWORD" eventpipe_postgres `
  psql -h 127.0.0.1 -U eventpipe -d eventpipe -tAc `
  "select version_num from alembic_version;"
# 002_tenant_boundary
```

Tenant authorization and event round-trip:

```powershell
$env:NEXUS_EVENTS_TOKEN = '<short-lived owner JWT>'
$env:TENANT_A = '<tenant A UUID>'
$env:TENANT_B = '<tenant B UUID>'

@'
{"source":"nexuscore","event_type":"ai.job.observed","payload":{"job_id":"00000000-0000-4000-8000-000000000004","ingress_event_id":"00000000-0000-4000-8000-000000000003","state":"completed","attempts":1},"metadata":{}}
'@ | Set-Content -Encoding utf8 "$env:TEMP\root-probe.json"

# Missing bearer: 401
curl.exe -s -o NUL -w "%{http_code}" -X POST http://127.0.0.1:28013/api/v1/events `
  -H "Content-Type: application/json" --data-binary "@$env:TEMP\root-probe.json"

# Owner: 200 and an EventPipe storage UUID
curl.exe -s -X POST http://127.0.0.1:28013/api/v1/events `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer $env:NEXUS_EVENTS_TOKEN" `
  -H "X-Tenant-ID: $env:TENANT_A" `
  --data-binary "@$env:TEMP\root-probe.json"

# Foreign tenant: 404
curl.exe -s -o NUL -w "%{http_code}" -X POST http://127.0.0.1:28013/api/v1/events `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer $env:NEXUS_EVENTS_TOKEN" `
  -H "X-Tenant-ID: $env:TENANT_B" `
  --data-binary "@$env:TEMP\root-probe.json"

# Use an owner who is a member of both tenants. If B is not a member, a 404 is
# also an acceptable denial; a 200 with A's rows is not.
# Tenant A sees its event; tenant B sees an empty list.
curl.exe -fsS "http://127.0.0.1:28020/api/v1/events?source=nexuscore&page=1&size=50" `
  -H "Authorization: Bearer $env:NEXUS_EVENTS_TOKEN" `
  -H "X-Tenant-ID: $env:TENANT_A"
curl.exe -fsS "http://127.0.0.1:28020/api/v1/events?source=nexuscore&page=1&size=50" `
  -H "Authorization: Bearer $env:NEXUS_EVENTS_TOKEN" `
  -H "X-Tenant-ID: $env:TENANT_B"
```

Kafka backpressure:

```powershell
docker compose --profile observability-events stop kafka
# The POST must return 503 within the 5 s producer timeout, not a false 200.
docker compose --profile observability-events start kafka
```

DLQ:

```powershell
@"
{"event_id":"probe","source":"","event_type":"ai.job.observed","timestamp":"2026-11-11T00:00:00+00:00","tenant_id":"$env:TENANT_A"}
"@ | Set-Content -Encoding utf8 "$env:TEMP\root-dlq.json"
Get-Content "$env:TEMP\root-dlq.json" -Raw |
  docker compose exec -T kafka kafka-console-producer --bootstrap-server kafka:9092 --topic events.raw

# Wait for transform to process the invalid record, then inspect the DLQ count.
curl.exe -fsS http://127.0.0.1:28020/api/v1/stats `
  -H "Authorization: Bearer $env:NEXUS_EVENTS_TOKEN" `
  -H "X-Tenant-ID: $env:TENANT_A"
# dlq_count must increase; no raw input or exception text appears in the response.
```

Known non-gate for Stage 1: posting the same body twice creates two storage
events because EventPipe generates its own storage ID. Record the duplicate count
as evidence, do not call it idempotent. The Stage 3 gate is one row per
`(tenant_id, envelope.event_id)`.

### 8.3 Stage 2 — PipeWatch root profile and relay

```powershell
$env:PIPEWATCH_CLICKHOUSE_PASSWORD = '<clickhouse password>'
docker compose --profile observability-logs config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Invalid observability-logs Compose configuration' }

docker compose --profile observability-logs up -d --wait --wait-timeout 300 `
  pipewatch_clickhouse pipewatch_redis
docker compose --profile observability-logs up -d --wait --wait-timeout 300 pipewatch
docker compose --profile observability-logs ps
```

Health, durability and TTL:

```powershell
curl.exe -fsS http://127.0.0.1:28084/health   # {"status":"ok"}
curl.exe -fsS http://127.0.0.1:28084/ready    # {"status":"ready"}
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:28084/metrics
# 404: tenant/platform metrics are not exposed

docker compose exec pipewatch_redis redis-cli CONFIG GET appendonly appendfsync maxmemory-policy
# appendonly yes; appendfsync always; maxmemory-policy noeviction
# Current PipeWatch config has no Redis password setting; the service is
# internal-only and unpublished. Do not expose this port.

docker compose exec pipewatch_clickhouse clickhouse-client `
  --password "$env:PIPEWATCH_CLICKHOUSE_PASSWORD" --query `
  "SELECT create_table_query FROM system.tables WHERE database='pipewatch' AND name='logs'" |
  Select-String "INTERVAL 30 DAY"
```

Relay against the root loopback ports:

```powershell
$env:NEXUS_EVENTS_TOKEN = '<short-lived owner JWT>'
$env:OBSERVABILITY_STATE = '<persistent operator-controlled path>\relay.sqlite'
$env:TENANT_A = '<tenant A UUID>'
$env:BOT_A = '<bot A UUID>'
$py = 'D:\Programming\NexusCore\.venv\tooling-checks\Scripts\python.exe'
$relayArgs = @(
  '--agent-origin', 'http://127.0.0.1:8014',
  '--auth-origin', 'http://127.0.0.1:28080',
  '--webhook-origin', 'http://127.0.0.1:8001',
  '--eventpipe-origin', 'http://127.0.0.1:28013',
  '--pipewatch-origin', 'http://127.0.0.1:28084',
  '--tenant-id', $env:TENANT_A,
  '--bot-id', $env:BOT_A,
  '--state', $env:OBSERVABILITY_STATE
)

& $py -B scripts/relay_observability.py @relayArgs
if ($LASTEXITCODE -ne 0) { throw 'Relay sweep failed' }
# Expected: pending=0, unknown=0, accepted=2 * number of observed events.

# Repeat with the same state; accepted must not grow and no new rows may appear.
& $py -B scripts/relay_observability.py @relayArgs
if ($LASTEXITCODE -ne 0) { throw 'Relay repeat failed' }
```

Then verify both sinks:

```powershell
curl.exe -fsS "http://127.0.0.1:28020/api/v1/events?source=nexuscore&page=1&size=50" `
  -H "Authorization: Bearer $env:NEXUS_EVENTS_TOKEN" `
  -H "X-Tenant-ID: $env:TENANT_A"
curl.exe -fsS "http://127.0.0.1:28084/api/v1/logs?service=nexuscore&page=1&size=50" `
  -H "Authorization: Bearer $env:NEXUS_EVENTS_TOKEN" `
  -H "X-Tenant-ID: $env:TENANT_A"
```

Tenant B must get an empty list from each when the test owner is a member of B;
if not, 404 is the expected denial. An EventPipe detail/raw request by a storage
UUID seen under tenant B must return 404.

Outage and reconciliation:

```powershell
docker compose --profile observability-events stop eventpipe_ingest
& $py -B scripts/relay_observability.py @relayArgs
# Expect exit 1, unknown>=1 for EventPipe, PipeWatch still accepted.
# Do not retry the same unknown automatically.
docker compose --profile observability-events start eventpipe_ingest
& $py -B scripts/relay_observability.py @relayArgs `
  --reconcile --eventpipe-query-origin http://127.0.0.1:28020
# Exit 0 only if every unknown is confirmed; unresolved=1 is the honest result
# when EventPipe never accepted the event.
```

Backpressure test with a separate, bounded test override (planned test file, not
a production setting):

```powershell
# docker-compose.observability-test.yml sets APP_QUEUE_MAXSIZE=2 and
# APP_BATCH_SIZE=1 on a disposable profile.
docker compose -f docker-compose.yml -f docker-compose.observability-test.yml `
  --profile observability-logs up -d --wait pipewatch_clickhouse pipewatch_redis pipewatch
docker compose -f docker-compose.yml -f docker-compose.observability-test.yml `
  stop pipewatch_clickhouse
# Post three logs. The third must return 429; no request may return 200 and then
# silently drop the record. Restart ClickHouse and verify the backlog drains.
```

Alert cooldown:

```powershell
# Create one rule with threshold=1 and cooldown_minutes=5, send ten matching logs,
# then read /api/v1/alerts/events. Exactly one event per rule/window is allowed;
# no Telegram call is made in platform mode.
```

### 8.4 Stage 3 — gates that must fail on the current tree

These are target checks. Running them before implementation must produce the
documented failure, not a false pass.

```powershell
# 1. Consumer idempotency: post the same envelope event_id twice.
#    EventPipe: select count(*) ... where payload->>'event_id' = '<event_id>' is 1.
#    PipeWatch: /api/v1/logs?trace_id=<event_id> total is 1.
#    Current expected failure: 2 in both.

# 2. Relay rejected/retry: stop EventPipe ingest, run one sweep.
#    Target: state=rejected, next_attempt_at set, exit 1; after recovery, retry
#    sends once and stores one row. Current expected failure: unknown, no retry.

# 3. Retention: insert one old and one current synthetic row, run the cleanup
#    dry run. Target: exactly the old row is selected; no cross-tenant delete.
#    Current expected failure: no cleanup job exists.

# 4. Alert cap: create enough rules to exceed the per-tenant budget.
#    Target: notifications stop at the cap, suppressed counter increases.
#    Current expected failure: no cap exists.

# 5. Machine credential: run the relay for 24 h without a human JWT.
#    Target: short-lived service token with rotation and revocation.
#    Current expected failure: no service principal exists.
```

## 9. What is explicitly NOT included

- No raw application stdout/stderr shipping, no Docker socket mount, no Vector,
  Fluent Bit, Filebeat or similar agent.
- No new event types beyond the three in §3.2. No message/answer content, prompt
  text, auth audit, login history, billing, token cost or Telegram identity.
- No changes to AuthFortress, WebHook Manager or AgentHub code, schemas or data.
  No producer is embedded into them.
- No reuse of root PostgreSQL or root Redis. No migration of existing root data.
- No Prometheus, Grafana, Alertmanager or dashboard changes in the root. The
  sibling monitoring stacks stay standalone.
- No Telegram notifications, no real Telegram, LLM or provider calls.
- No exactly-once guarantee. The supported guarantee is at-least-once with
  relay-side no-resend and read-time deduplication.
- No automatic replay of `unknown`, DLQ or dead letters.
- No automatic retention deletion in this document; §5.4 is policy only.
- No production TLS, reverse proxy, VPS, public ingress or off-host backup.
- No HA, multi-broker Kafka, ClickHouse cluster, Redis Sentinel or load
  certification. Single instances are a local demo boundary.
- No containerised relay, no Compose DNS origins and no machine credential until
  Stage 3 is separately approved.
- No merge of the EventPipe/PipeWatch repositories into NexusCore and no sibling
  Compose rewrite.

## 10. Blockers and decisions required

1. **Machine credential (Blocked).** AuthFortress has no service principal for
   `tenant.manage`; the only service key gates `/internal/tenants/{id}/status`.
   EventPipe/PipeWatch require a bearer JWT and call the tenant authorize
   endpoint. A 24/7 relay cannot use a human owner JWT safely. Needed: a
   short-lived, tenant-scoped service credential with rotation, revocation and
   audit. This is a separate AuthFortress contract.
2. **Relay origin policy (Blocked for containerisation).** The relay accepts
   only numeric IPv4 loopback/RFC1918 origins. Root Compose service names are
   DNS names. Stage 2 keeps the relay on the host with loopback ports; Stage 3
   needs either an exact internal-host allowlist or a different transport. Do
   not weaken the validator to arbitrary DNS.
3. **Consumer idempotency design (Blocked).** EventPipe needs an optional
   caller-supplied event ID and a unique `(tenant_id, event_id)` constraint;
   PipeWatch needs a dedup key and a ClickHouse strategy (`ReplacingMergeTree`
   or a Redis claim). Both are sibling changes with separate acceptance.
4. **Retention values (Decision required).** The 7/14/30-day values in §5.4 are
   proposals. Data deletion needs approval, a dry-run and a restore story.
5. **PipeWatch payload scope (Decision required).** This document limits
   PipeWatch to relay envelopes (`service=nexuscore`). Collecting real
   application logs requires app-side tenant attribution and a bounded shipper;
   it is not safe to infer tenant from container names or log text.
6. **Alert notification channel (Decision required).** The root keeps
   notifications disabled. If a webhook or Telegram channel is enabled later,
   it needs a tenant-owned credential and the storm cap from §6.3 first.
7. **PipeWatch Redis authentication (Blocked for production).** The current
   PipeWatch configuration has no Redis password setting. The local root profile
   keeps `pipewatch_redis` on an internal network with no published port. A
   production deployment needs a sibling change and a credential contract before
   the Redis port can be shared or exposed.

## 11. Review references

- [README request flow and next work](../README.md)
- [Observability relay contract](observability-flow.md)
- [Identity/bot source extension](observability-identity-bots.md)
- [Read-only reconciliation](observability-reconciliation.md)
- [Relay runbook](../docs/observability-flow.md)
- [2026-10-22 acceptance](../docs/observability-acceptance-2026-10-22.md)
- [2026-10-22 identity/bot acceptance](../docs/observability-identity-bots-2026-10-22.md)
- [2026-10-23 reconciliation acceptance](../docs/observability-reconciliation-2026-10-23.md)
- [Dashboard Overview contract](dashboard-overview.md)
- [Dashboard Events contract](dashboard-events.md)
- [EventPipe repository](https://github.com/sayomiyori/EventPipe) and its
  `README.md`, `specs/local-hardening.md`
- [PipeWatch repository](https://github.com/sayomiyori/PipeWatch) and its
  `README.md`, `specs/local-hardening.md`
- AuthFortress `app/api/v1/tenants.py` and `app/api/internal.py` (bearer-only
  tenant authorization; service key is limited to tenant status)
