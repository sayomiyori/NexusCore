# NexusCore shared observability stream

`scripts/relay_observability.py` forwards tenant-authorized AuthFortress tenant,
WebHook bot and AgentHub AI job observations to existing EventPipe and PipeWatch
APIs. No sibling imports,
service changes, new dependencies or default root activation are required.
See [the contract](../specs/observability-flow.md).

```text
AuthFortress tenants / WebHook bots / AgentHub jobs
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
approved. If selected, AgentHub needs `PLATFORM_READ_ENABLED=true`, valid issuer/bot-context
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

### Optional identity and registry sources

The AI-only example above remains unchanged and can reopen its existing state.
At least one source origin must be supplied; `--agent-origin` is now optional.
To select all three sources, add `--auth-origin http://127.0.0.1:38080` and
`--webhook-origin http://127.0.0.1:38001`, using separately inspected isolated
origins. For just identity/registry observations, omit `--agent-origin`.
Tenant/bot arguments remain required even in auth-only mode; auth envelopes have
null bot scope and do not imply a relationship to the selected bot.

Changing the selected source origins changes the state binding. Start this new
source configuration with a deliberately selected new state path, for example
`.venv/identity-bots.sqlite`; do not overwrite/reset or modify existing state.
This can replay observations from sources included in both configurations, so
do not concurrently enable overlapping relays without accounting for that fact.

AuthFortress uses `GET /api/v1/tenants/{tenant_id}`. Only canonical tenant UUID,
creation time and owner/member role are consumed; tenant name is discarded.
`auth.tenant.observed` carries `tenant_created_at` and `observed_role`, with the
tenant UUID as correlation reference and first local observation time as event
time. Stable identity excludes polling time and selected bot; repeated reads
retain the original saved envelope. This is a snapshot of the caller's observed
tenant access, not evidence of a login, logout or timed membership change.

WebHook uses `GET /api/v1/tenants/{tenant_id}/bots/{bot_id}` with
`PLATFORM_BOTS_ENABLED=true` and existing online identity configuration. Telegram
intake/reply flags need not be enabled. `webhook.bot.observed` retains only strict
`is_active` and the known `webhook_status`, with matching canonical tenant/bot,
UTC source update time and bot UUID as correlation reference. Names, username,
numeric Telegram identity, credentials and webhook URL are discarded.

Each configured source independently completes a fresh authorized read/scan.
Only its event types may then drain pending rows. One denied/unavailable source
does not block independently authorized types: an inactive bot can deny AI reads
while its registry deactivation snapshot is delivered. Partial failures add
`source_errors` to the cumulative counts and exit 1; all-source failure prints
only the existing static diagnostic and makes no sink calls. The interval loop
repeats only fully successful sweeps. No producer failure is silently hidden.

Both sinks use the actual envelope type as event_type/fixed message. EventPipe
scalar metadata omits bot_id for auth observations; PipeWatch stores the same
full envelope. Webhook failed/unknown states get error severity. Accepted/unknown
deliveries keep the same no-automatic-resend behavior. Existing SQLite schema
and original AI event IDs are unchanged.

The SQLite file belongs to this relay only. Do not select a service database,
edit its rows, share it between different destinations/scopes or delete it to
clear an error. State binds tenant, bot and all configured origins; changing any
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
successful authorization/scan of their own source, even if that job no longer appears in a scan.

If `unknown` is nonzero, inspect the destination through its authorized query
API using the deterministic envelope UUID (`relay_event_id` / `trace_id`). A
matching record can establish acceptance; an absent query result alone cannot
exclude delayed Kafka/Redis processing. Use the explicit read-only reconciliation
report below; there is no automatic retry/reset or state-update command. Do not
manually rewrite state or start with an empty file to make the count disappear. Neither
sink accepts a caller-provided idempotency key, so this cannot guarantee
exactly-once storage. PipeWatch's own ambiguous ClickHouse replay remains at least
once even after the relay received an acceptance receipt.

## Read-only unknown reconciliation

Use the **same** tenant/bot, selected source/sink origins and existing state path
as the original relay. Add `--reconcile --eventpipe-query-origin ORIGIN`, selecting
the authorized query API for that bound EventPipe ingest deployment. Query and
ingest may use different ports. That explicit query origin is validated like
other private origins; it does not change the existing state identity. Pairing
it with the correct deployment remains the operator's responsibility.

```powershell
& ../WebHook_Manager/.venv/Scripts/python.exe -B scripts/relay_observability.py `
  --agent-origin http://127.0.0.1:38014 `
  --eventpipe-origin http://127.0.0.1:38013 `
  --pipewatch-origin http://127.0.0.1:38084 `
  --tenant-id 00000000-0000-4000-8000-000000000001 `
  --bot-id 00000000-0000-4000-8000-000000000002 `
  --state .venv/observability.sqlite `
  --reconcile --eventpipe-query-origin http://127.0.0.1:38015
```

Keep any original `--auth-origin`/`--webhook-origin` too. The token still comes
only from `NEXUS_EVENTS_TOKEN`; the current receiver tenant-read APIs enforce
authorization. No source API is called, so an inactive bot does not hide its
historical evidence. Query origin without reconcile, missing query origin and
`--interval` with reconcile fail before HTTP.

The mode reads existing rollback-journal SQLite through `mode=ro`, validates
its binding and reconstructs selected envelopes with the original ID/schema/
scope builders. Missing/nonregular/link paths and WAL format fail closed before
SQLite opens (WAL readers can write shared-memory sidecars). It creates no new
state, migration or receipt and changes no accepted/pending/unknown rows. Use
trusted local parent directories and the relay's default journal format; do not
change journal mode on deployment data to bypass an error.

Only `unknown` rows are selected, at most 100 per report. Output contains five
integer delivery counts, without tokens, identifiers, payloads or raw errors:

| Count | Evidence |
| --- | --- |
| `confirmed` | One observed stored record has the complete exact envelope and receiver mapping |
| `unresolved` | No matching record was observed; this does not prove non-delivery |
| `duplicates` | More than one matching stored record was observed |
| `conflicts` | A record claims the ID but differs in complete payload or mapping; takes precedence over duplicate/confirmed |
| `errors` | Receiver denial/outage, invalid response or incomplete bounded scan prevented a conclusion |

Exit 0 means every selected unknown is confirmed, or there were none. Any other
category exits 1. Successful reporting leaves unknown rows unknown; repeating
it or the normal relay cannot resend them. Confirmation establishes observed
presence, not exactly-once delivery, uniqueness under concurrent writes or a
permission to alter state. A persistence/reset/resend workflow is not provided.

EventPipe lists `source=nexuscore` in pages of 100, reads every full detail and
compares full envelope plus source/type/relay metadata, never preview text.
The scan is shared by all selected EventPipe checks and must finish within ten
pages/1,000 summaries; a full last page, repeated storage UUID or invalid detail
makes those checks errors. List offsets can move during traffic; rerun after
processing settles. The worst case is ten list and 1,000 detail GETs; socket
timeouts are not an overall deadline. No configurable unlimited scan is added.

PipeWatch queries each unknown's canonical `trace_id`, `service=nexuscore`, page 1
and size 2, validates count/page consistency and full metadata. Count/trace alone
cannot confirm delivery. Errors in one receiver do not suppress checks of the
other. This mode never POSTs, retries delivery or removes evidence. See the
[reconciliation contract](../specs/observability-reconciliation.md).
The [2026-10-23 acceptance](observability-reconciliation-2026-10-23.md) records
actual lost receipts, GET-only reports, storage/state preservation and failures.

## Local checks

```powershell
& .venv/tooling-checks/Scripts/python.exe -B -m unittest discover -s tests -p test_verify_observability.py -q
& .venv/tooling-checks/Scripts/python.exe -B -m unittest discover -s tests -p test_verify_observability_reconciliation.py -q
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
The [identity/bot extension acceptance](observability-identity-bots-2026-10-22.md)
adds the actual three-source drill, inactive bot/source failures and preservation
of the existing 580-container baseline.

The identity/registry extension follows the
[source contract](../specs/observability-identity-bots.md). These snapshots do not
export global AuthFortress admin audit, legacy API-key events, ingress/delivery
payloads or every intermediate lifecycle change. They do not replace business
delivery, configure Prometheus/Grafana or add a dashboard. Live provider
quality, production deployment, service credentials/refresh and sustained load
remain separate work. Default root flags and existing data are unchanged.
