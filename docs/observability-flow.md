# NexusCore shared observability stream

`scripts/relay_observability.py` forwards tenant-authorized AgentHub AI job
observations to existing EventPipe and PipeWatch APIs. No sibling imports,
service changes, new dependencies or default root activation are required.
See [the contract](../specs/observability-flow.md).

```text
AgentHub authorized job metadata
               |
     NexusCore local durable relay
               |
        +------+------+
        |             |
    EventPipe      PipeWatch
      Kafka         Redis
   PostgreSQL/S3  ClickHouse/live stream
```

## Configuration and operation

Use only a separately provisioned isolated stack until a deployment is explicitly
approved. AgentHub needs `PLATFORM_READ_ENABLED=true`, valid issuer/bot-context
configuration and its existing platform schema. EventPipe ingest/transform/query
need their platform modes and checked schema. PipeWatch needs
`PLATFORM_AUTH_ENABLED=true`, the issuer URL and persistent Redis with AOF,
`appendfsync=always`, no eviction. The two sinks require `tenant.manage`, so use
an owner access JWT. A member's source read permission does not grant sink writes.
Standalone sinks do not provide the required tenant boundary; do not point this
relay at them. This command does not turn on any of these modes itself.

For the cached EventPipe ingest image used by this acceptance, launch its existing
ASGI app with `python -m uvicorn ingest_service.app.main:app --host 0.0.0.0
--port 8000`. Its lifespan starts/closes Kafka and gRPC. The image's default dual
CLI waited for gRPC termination after HTTP shutdown and required a forced stop;
the integration uses the existing ASGI lifecycle instead. This does not change
the standalone image or authorize recreating any existing service container.

Supply the access token through process environment `NEXUS_EVENTS_TOKEN`, using
your secret provisioning mechanism. The relay does not login, refresh tokens or
read `.env`. Token expiry/revocation stops a sweep. Run with the existing Python
environment containing `httpx` and `pydantic`, for example WebHook Manager's venv.

```powershell
# Replace these synthetic UUIDs and numeric origins with the isolated deployment.
# The state parent directory must already exist and be operator-controlled.
& ../WebHook_Manager/.venv/Scripts/python.exe -B scripts/relay_observability.py `
  --agent-origin http://127.0.0.1:38014 `
  --eventpipe-origin http://127.0.0.1:38013 `
  --pipewatch-origin http://127.0.0.1:38084 `
  --tenant-id 00000000-0000-4000-8000-000000000001 `
  --bot-id 00000000-0000-4000-8000-000000000002 `
  --state .venv/observability.sqlite
```

Default is one sweep. Append `--interval 15` for repeated successful sweeps;
allowed intervals are 5..3600 seconds. Any failed sweep exits 1. Success prints
only cumulative `pending`, `accepted`, `unknown` delivery counts, not event or
credential contents. Two accepted deliveries normally represent one observation.
Invalid CLI syntax exits 2 with static diagnostics; Ctrl+C exits 130.

Only explicit IPv4 loopback/RFC1918 HTTP(S) origins are accepted. Paths are fixed;
URL credentials, DNS names, redirects, proxy environment and compressed responses
are rejected. Each raw response is capped at 256 KiB; socket timeout is five
seconds, connect timeout two. This is an inactivity timeout, not an absolute
whole-sweep deadline. Use private trusted endpoints; this is not a URL fetch API.

The SQLite file belongs to this relay only. Do not select a service database,
edit its rows, share it between different destinations/scopes or delete it to
clear an error. State binds tenant, bot and all three origins; changing any
requires a deliberate new relay identity and may replay old observations.
Trusted parent directories and local filesystem are required; final-component
links/nonregular files are rejected. State uses local SQLite locking/transactions
and contains safe envelopes and receiver UUIDs, never JWTs or message text.
Concurrent processes sharing this file claim each pending delivery at most once.
Protect and back up the file separately; there is no automatic retention/deletion.

## Event and failure semantics

Every `ai.job.observed` envelope includes version, deterministic event/idempotency
UUID, canonical tenant/bot, UTC observed-job timestamp and ingress event UUID as
this stream's correlation reference. Payload includes only job ID, ingress ID,
validated state and attempts. The original source correlation ID is not exposed
by the job metadata API and is not reconstructed. Provider/model names, messages,
answers and free-form errors are discarded.

EventPipe stores the envelope in `payload` under its own assigned storage UUID;
scalar metadata also carries `relay_event_id` and bot ID. PipeWatch stores the
same envelope in `metadata`, uses the relay UUID as `trace_id`, fixed message
`ai.job.observed` and error severity for failed/unknown jobs. Its row timestamp
is ingestion time; original event time remains in the envelope. Query through
the existing tenant-authorized APIs and correlate by the relay UUID.

Every sweep rescans UUID-keyset pages from the beginning. It therefore sees
updates to old jobs and new randomly ordered UUIDs. Maximum 100 pages/10,000
jobs per sweep; overflow fails explicitly before draining. Polling can miss
intermediate state transitions; these are observations, not a complete audit log.

The envelope and two pending rows commit before delivery. Each pending row
becomes `unknown` in a committed transaction before its HTTP call. Only a valid
accepted receipt changes it to `accepted`. Accepted/unknown rows are never
automatically resent. The other sink can still accept its copy after one fails.
Pending rows survive interrupted collection and resume only after a fresh
successful source authorization, even if that job no longer appears in a scan.

If `unknown` is nonzero, inspect the destination through its authorized query
API using the deterministic envelope UUID (`relay_event_id` / `trace_id`). A
matching record can establish acceptance; an absent query result alone cannot
exclude delayed Kafka/Redis processing. There is no automatic retry/reset command:
reconciliation needs a separate reviewed operator procedure. Do not manually
rewrite state or start with an empty file to make the count disappear. Neither
sink accepts a caller-provided idempotency key, so this cannot guarantee
exactly-once storage. PipeWatch's own ambiguous ClickHouse replay remains at least
once even after the relay received an acceptance receipt.

## Local checks

```powershell
& .venv/tooling-checks/Scripts/python.exe -B -m unittest discover -s tests -p test_verify_observability.py -q
& .venv/tooling-checks/Scripts/python.exe -B -m unittest discover -s tests -p 'test_verify*.py' -q
& .venv/tooling-checks/Scripts/python.exe -B -m ruff check --no-cache scripts tests
& .venv/tooling-checks/Scripts/python.exe -m compileall -q scripts tests
```

The controlled tests use real SQLite and mocked HTTP boundaries. They cover
safe payloads, cursor/schema/UTC/body limits, duplicate/concurrent claims, process
reopen, pending recovery, sink isolation, uncertain receipts, source denial,
state binding and credential-safe CLI failures. The
[2026-10-22 Docker acceptance](observability-acceptance-2026-10-22.md) records the
actual issuer/source, both storage pipelines and exact preservation results.

This first stream does not emit all AuthFortress/WebHook lifecycle events, replace
business delivery, configure Prometheus/Grafana or add a dashboard. Live provider
quality, production deployment, service credentials/refresh and sustained load
remain separate work. Default root flags and existing data are unchanged.
