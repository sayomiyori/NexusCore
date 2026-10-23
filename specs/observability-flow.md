# NexusCore shared observability flow v1

The implemented [identity/bot source extension](observability-identity-bots.md)
adds optional AuthFortress/WebHook sources and per-source authorization gating.
The original AI-only contract and identity/state format below remain compatible.
Explicit [read-only unknown reconciliation](observability-reconciliation.md)
checks existing receiver evidence without resending or rewriting relay state.

Connect the existing tenant-authorized AgentHub job metadata API to both
EventPipe and PipeWatch, without changing sibling services or existing runtime.
This first stream reports observed AI job states, not private messages, answers,
credentials, all intermediate transitions, auth audit records or billing.

## Existing contracts and safe defaults

- Source: `GET /api/v1/tenants/{tenant_id}/bots/{bot_id}/ai/jobs`, pages of 100.
  Online AuthFortress and canonical bot checks remain mandatory. Scan from the
  beginning on each sweep: random UUID ordering cannot be a durable time cursor.
- EventPipe: `POST /api/v1/events`, body `source`, `event_type`, `payload`, `metadata`.
  PipeWatch: `POST /api/v1/logs`, body `service`, `level`, `message`, `trace_id`,
  `metadata`. Both existing platform modes authorize the selected tenant through
  AuthFortress with `tenant.manage`; the relay therefore requires an owner JWT.
- Supply the JWT only through `NEXUS_EVENTS_TOKEN`, never CLI arguments, `.env`
  loading, logs or state. Origins are explicitly configured numeric loopback or
  RFC1918 HTTP(S) origins; no DNS, public/link-local destinations, proxy, redirect,
  URL credentials or caller-controlled paths. Socket timeout 5s/connect 2s;
  raw JSON responses at most 256 KiB and no compressed response bodies.
- A new operator-owned SQLite state file stores only safe event envelopes,
  destination identities and per-sink outcomes. Parent directories are trusted;
  final-component links/nonregular files are rejected. This is local relay state,
  not a service schema migration or permission to open deployment databases.
  Bind state to tenant, bot and all origins; changed identity fails closed.

## Envelope and delivery

`event_type=ai.job.observed`, `schema_version=1`, tenant/bot UUIDs, UTC occurred
time from the observed job, deterministic event/idempotency UUID based on scope,
job ID/state/attempts/updated time. `correlation_id` is the source ingress event
UUID for this stream; the source metadata API does not expose its original
envelope correlation ID. Payload allowlists job/ingress UUIDs, state and attempts.
No provider/model names, request bodies, free-form errors or response text.
Both sinks receive the same envelope in payload/metadata. PipeWatch trace ID is
the relay event UUID; its message is the fixed event type and severity is derived
from the validated job state. Its timestamp is ingestion time; original event
time stays in metadata. EventPipe generates its own storage event UUID.

Store the envelope and two pending deliveries atomically before sending.
Claim a pending delivery under a SQLite write transaction and commit `unknown`
before HTTP; record `accepted` only after the expected valid receipt. Replays,
two concurrent relay processes and partial sink failure must not resend accepted
or unknown deliveries. The other sink can still succeed. Neither sink supports
caller-supplied idempotency IDs, so lost HTTP receipts/crash after claim require
operator reconciliation. Do not promise exactly-once or blindly retry POST.
Unknown outcomes are visible as counts and a nonzero exit, without raw errors.
Persist pending deliveries so a later authenticated sweep can resume them even
if the source state changed. Pending work is sent only after a successful fresh
source authorization. A sweep is limited to 100 pages; overflow is an explicit
failure, not a complete scan. No automatic state deletion/retention.

CLI: `scripts/relay_observability.py --agent-origin ORIGIN --eventpipe-origin
ORIGIN --pipewatch-origin ORIGIN --tenant-id UUID --bot-id UUID --state PATH`.
Default one sweep; optional `--interval` 5..3600 seconds repeats successful
sweeps. Any failed sweep stops with static diagnostics. No default activation,
real Telegram/LLM, new dependency or existing-root Compose change.

## Acceptance

1. Unit checks: strict scope/schema/URL/body limits, safe payloads, pagination,
   same event in both sinks, repeat and concurrent dedup, pending recovery,
   independent sink failures, unknown outcomes, state identity binding,
   invalid/revoked/foreign scope, and static CLI/transport diagnostics.
2. New UUID internal Docker fixture with synthetic issuer/tenant/bot/job, actual
   EventPipe Kafka/transform/PostgreSQL/S3 and PipeWatch Redis/ClickHouse. Read
   both results through authorized APIs and reject cross-tenant reads. Repeated
   relay adds no accepted duplicates; a failed sink does not duplicate the other.
3. Compare every existing resource and main data/config/WSL fingerprints before
   and after; stop only owned new containers, retain all data. No root rollout,
   cleanup, provider traffic or shared Docker restart.
4. Root regression/lint/compile, independent adversarial/security review, scoped
   commit and push. Document observed-state gaps, JWT expiry, receipt ambiguity
   and local verification limits.

No blocking design question remains: use existing online owner authorization and
metadata-only polling rather than adding service credentials or modifying dirty
producer repositories. Later event types and production credential provisioning
require separate contracts and acceptance.
