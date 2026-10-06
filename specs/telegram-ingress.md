# Telegram webhook admission and durable publication v1

Status: Approved on 2026-10-05. Implemented and locally verified on 2026-10-06.
Parent: [integration-contracts.md](integration-contracts.md).
Prerequisite: locally verified [bot-registration.md](bot-registration.md).
Verification: WebHook Manager 238 tests, 84.03% coverage, Ruff/strict Mypy,
isolated migration roundtrip, built API/worker/scanner controlled HTTP acceptance,
and independent read-only review. Live Telegram setup, AgentHub AI consumption
and outgoing answers remain unverified and outside this contract's scope.

## Goal and boundary

Advance the first real Telegram -> AI -> reply scenario by implementing its
Telegram intake boundary in WebHook Manager. Accept authenticated updates,
persist canonical tenant/bot context and normalized events, and reliably submit
them to the future AgentHub admission endpoint. No LLM or outgoing Telegram
message runs in this step. Acceptance uses a controlled HTTP admission receiver;
actual AgentHub consumer and answer delivery are subsequent contracts.

Existing standalone `/api/v1/ingest/{source_slug}` and delivery tasks stay intact.
Do not backfill legacy users, sources or events into platform tenants. Services
remain independent repositories; no imports from AuthFortress or AgentHub.

## Inspected baseline and selected approach

WebHook Manager main `7b3a039` has issuer authorization/status clients, encrypted
bot credentials, scoped bot routes and sync/async SQLAlchemy sessions. Its
legacy ingest handler persists an event then uses BackgroundTasks to dispatch
Celery deliveries; that leaves a crash/broker-failure gap and cannot authenticate
Telegram's secret-token header. The legacy tables do not carry platform scope.

Options considered:

- Direct AgentHub HTTP in webhook: slow acknowledgement and remote outage coupling.
- Redis-only queue: loses admission durability on broker loss/restart.
- Selected: atomic PostgreSQL ingress + outbox; existing Redis/Celery transport,
  with independent database recovery. No new library or broker dependency.

## Feature configuration and rollout

Add `PLATFORM_TELEGRAM_ENABLED=false`, separate from `PLATFORM_BOTS_ENABLED`.
When enabled, bot registration configuration must already be valid, and:

- `TELEGRAM_WEBHOOK_ORIGIN`: fixed operator-configured HTTPS origin, no credentials,
  path, query or fragment; public DNS name, supported port 443/80/88/8443.
  Never accept a webhook URL, IP override or certificate from a user request.
- `AGENTHUB_BASE_URL`: fixed origin with the existing issuer URL validation policy,
  adapted to allow Compose `agent_service`; HTTPS outside local development.
- `WEBHOOK_AGENT_INGRESS_KEY`: independent random ASCII secret, 32..256 bytes;
  distinct from token-encryption, issuer, context and legacy signing keys.
- `PLATFORM_PUBLICATION_MAX_ATTEMPTS=10`: bounded 1..100.

Disabled new routes return static 503; no provisioning occurs at startup.
Update service/root safe env examples and Compose forwarding. Only processes
which need decryption receive BOT_CREDENTIALS_KEY. Production/public exposure
is outside acceptance; first live provisioning needs a reviewed demo HTTPS URL.

## Explicit webhook provisioning

Add owner-only `POST /api/v1/tenants/{tenant_id}/bots/{bot_id}/webhook`.
Body is exactly `{ "dry_run": true|false }`, strict and limited to 4 KiB;
unknown fields and validation failures use sanitized 422 responses.
Resolve the bot with authorized tenant scope; inactive bot/tenant returns 403.

Dry run returns 200 with `{bot_id, tenant_id, webhook_url, operation: "setWebhook",
dry_run: true}`. It does not persist a secret or call Telegram. The apply operation
returns 200 with `{bot_id, tenant_id, webhook_url, webhook_status}` after success.
Do not return a bot token, webhook secret, ciphertext or provider description.
Extend BotView.webhook_status from its existing constant to the persisted status:
`not_configured`, `configuring`, `configured`, `failed`, `unknown`.

Generate one independent 32-byte URL-safe secret for the bot's initial setup.
Encrypt a purpose-tagged payload bound to tenant and bot with the configured
Fernet key; store SHA256(secret) for constant-time incoming verification.
Persist the secret and configuring state before the external request. v1 has no
secret rotation, URL replacement, deleteWebhook or drop_pending_updates operation.
Concurrent setup requests are serialized with a database claim, returning 409
while a claim is live. Claim expiry is 60 seconds and uses database time.

Reauthorize the owner and fresh active bot before applying. POST Telegram
setWebhook with the fixed URL `/webhooks/telegram/{bot_id}`, persisted secret,
allowed_updates=["message"], drop_pending_updates=false, max_connections=10.
Reuse bounded TLS-verifying HTTP behavior and credential-safe telemetry.
Only HTTP 200, ok=true, result=true establishes configured state. Invalid token
is static 400; other confirmed permanent rejection is static 502 and failed state;
timeouts, ambiguous server errors or interrupted claims yield unknown, static 503.
No automatic retry. An explicit repeated apply reuses exactly the same URL and
secret; configured calls return stored state without another external mutation.
Auth failure before the external call releases the claim without provisioning.
State updates are fenced by claim identity; a stale caller cannot overwrite a
new claim. The webhook secret remains usable while configuring/unknown to accept
updates that arrive before the external call's result is persisted.

Deactivation blocks intake/publication locally and does not delete the Telegram
webhook. No distributed atomic revocation guarantee is asserted. getWebhookInfo
may diagnose the remote URL, but cannot prove the installed secret or by itself
resolve unknown configuration to configured.

## Telegram admission route

Add `POST /webhooks/telegram/{bot_id}`. Route lookup supplies tenant_id; neither
headers nor raw JSON supply platform identity. Before parsing payload, check
feature enablement, bot lookup and exactly one X-Telegram-Bot-Api-Secret-Token
header with valid ASCII URL-safe format, length 1..256; compare its SHA256 in
constant time. Missing/wrong/repeated credentials return static 401. Unknown bot
returns 404; unprepared secret returns 403. No positive authorization cache.
Check fresh bot activity and AuthFortress tenant status, then reread bot state.
Inactive context returns 403; issuer outage returns static 503.

Read the body as a stream, rejecting above 1 MiB with 413 without buffering the
remainder. Require application/json (parameters allowed), UTF-8 object JSON,
no duplicate keys, NaN or infinities. Malformed data returns sanitized 422,
unsupported Content-Encoding/Content-Type returns 415. Never persist incoming
headers or log raw body/text. Use strict signed 64-bit IDs; bool is not an integer.
update_id must be present. Do not require monotonically increasing values.

Process only a new message in private chat, with nonempty non-whitespace text,
chat.id and positive message.message_id. Preserve original text, maximum 4096
characters. Known message fields with wrong types/ranges return 422. Structurally
valid other update kinds, non-private messages and media-only messages are
persisted as ignored, acknowledged 200, and never create publication work.
An update containing multiple recognized event kinds is malformed. Optional
unrelated Telegram fields are tolerated; they cannot override normalized context.

Persist raw JSON under canonical tenant/bot scope and a SHA256 canonical JSON
digest (sorted keys, UTF-8, compact separators; array order preserved). In one
transaction insert the ingress and, for supported messages, one outbox row.
Unique (bot_id, update_id) handles concurrent requests atomically. Replayed JSON
with the same semantic content returns the original event_id; changed content
for that identity returns static 409. Failed insert/commit returns static 503
and produces no queue publication or partial accepted record.

First supported admission returns 202 `{status: "accepted", event_id}` only after
commit. Ignored returns 200 `{status: "ignored", event_id}`. Replays return 200
`{status: "duplicate", event_id}`. These are acknowledgements of local durability,
not promises of AI completion. Broker outage does not change a committed response.

## Persistence and outgoing HTTP contract

Use a forward additive Alembic migration after `7b4a901f26c3`:

- `telegram_bot_webhooks`: bot_id PK/FK, tenant_id, encrypted secret, secret digest,
  fixed URL, state, claim UUID/deadline, created_at/updated_at.
- `telegram_ingress_events`: event UUID PK, tenant/bot UUIDs, update_id bigint,
  raw JSONB, digest, accepted/ignored state, immutable normalized envelope or null,
  correlation UUID and created_at. Unique (bot_id, update_id); scope/cursor index.
- `platform_ingress_outbox`: UUID PK, unique ingress FK, tenant/bot UUIDs, pending/
  processing/published/failed/cancelled state, attempts, next_attempt_at,
  claim UUID/deadline, published job UUID, static error code, timestamps.
  Index pending work and expired processing claims; nonnegative attempts starting
  at zero. A claim cannot increment above the configured maximum.

No cross-service FK. Local FKs preserve history (no cascade deletion). All reads
and claims validate matching local tenant/bot pairs. Persist the immutable v1
envelope described in the parent contract, with a server-generated event_id,
correlation_id, UTC occurred_at, key `telegram:<bot_id>:<update_id>`, and normalized
update_id/chat_id/message_id/question. Never include raw Telegram metadata or
credentials in this payload.

Submit that envelope to fixed `POST /internal/v1/telegram/updates` at AgentHub.
Serialize deterministic UTF-8 bytes and sign them with the existing HMAC helper
as `X-Webhook-Signature: sha256=<hex>` using WEBHOOK_AGENT_INGRESS_KEY. No forwarded
ingress credentials or headers. Receiver authenticates raw bytes before parsing.
This is a proposed downstream interface, implemented only in the next AI stage.

HTTP 202 for first durable remote admission and 200 for replay require a strict
response `{event_id: UUID, job_id: UUID, state: "pending"|"processing"|"completed"|
"failed"|"unknown"}` matching the submitted event. Only then mark published and
retain job_id. Published means remotely admitted, not successfully answered.
Redirects, oversized/encoded/malformed replies or mismatched event IDs never
finalize publication. Validate before persisting response identifiers; retain no
remote error body. HTTP 400/401/403/404/409/415/422 are terminal. Network timeout,
429, 5xx and invalid replies retry within the configured attempt limit, because
remote admission is idempotent for immutable event_id/key and must not run an LLM
synchronously. This retry policy does not apply to later LLM/sendMessage effects.

## Worker and recovery

Queue messages carry only outbox UUIDs. A separate database scanner
`python -m scripts.recover_platform_outbox --once` selects at most 100 due rows;
without --once it scans every 5 seconds. Compose adds one opt-in scanner process,
independent of Redis/Celery beat. Broker unavailability keeps rows durable and
due; scanner continues after recovery. Scanner does not mark rows published.

The Celery worker atomically claims a due pending or expired processing row with
a fresh claim UUID and 60-second lease; duplicate jobs cannot share a live claim.
Increment attempts on actual claimed processing, not queue submission. Check
fresh active context before HTTP; inactive context cancels the row, issuer outage
defers it with bounded attempts. Use explicit 15-second soft/20-second hard task
limits and bounded HTTP connect/read plus total 10-second timeout, TLS verification,
no redirects/proxies, bounded response bytes. Worker has no internal retry loop;
database next_attempt_at is authoritative. Backoff is min(2**attempt, 60) seconds;
valid 429 retry_after up to 3600 seconds overrides a shorter backoff. Exhaustion
is failed, visible in PostgreSQL. Fenced result updates reject stale claim owners.

Requeue expired claims after crashes. A crash after remote admission may repeat
the same immutable event; the receiver must reuse the durable job identity.
If the last allowed claim expires without a persisted result, mark failed with
static `admission_outcome_unconfirmed`; do not start an eleventh HTTP attempt at
the default cap. This state does not assert that remote admission never happened.
Pre-consumer acceptance uses a controlled idempotent receiver with this contract.
No manual replay API is added in this step; failed/cancelled rows are terminal.

## Acceptance and affected repositories

WebHook Manager: existing layered routes/services/repositories, schemas, Telegram
client, settings, DB metadata/new migration, Celery include/new task, recovery CLI,
README/env example, focused tests. NexusCore: root env/Compose service forwarding
and step status. AuthFortress and AgentHub production source stay untouched.

Verify against real PostgreSQL and Redis; only external HTTP boundaries use
doubles. Required checks:

1. Provisioning dry-run/no mutation, permissions/isolation, persisted independent
   secret/binding, successful response, concurrent claims, ambiguous outcome,
   explicit retry with identical payload, reauthorization and deactivation.
2. Valid private-text normalization, negative secrets, forged tenant fields,
   ignored updates, invalid IDs/JSON, streaming size boundary and safe telemetry.
3. Concurrent duplicate admission: one event/outbox, original event_id replay,
   409 for conflicting content; different bots can share update_id.
4. Atomic rollback, broker-down admission, scanner resume, duplicate jobs,
   crash/expired-lease recovery, stale fencing, inactive context cancellation,
   bounded retry/exhaustion, remote replay with one remote job.
5. Existing test suite, Ruff/strict Mypy, Docker API/worker/scanner startup and
   real HTTP -> PostgreSQL -> Redis/Celery -> controlled receiver smoke.
6. Fresh isolated migration upgrade/check. Downgrade/up requires a new explicit
   approval limited to a freshly created empty database with row-count guards.
7. Independent read-only adversarial review and scoped security pass before
   publishing verified task changes. No live webhook mutation before presenting
   the exact demo target and dry-run result for approval.

## References and remaining prerequisites

Telegram [setWebhook](https://core.telegram.org/bots/api#setwebhook) defines the
HTTPS destination, secret header and setup parameters. [Update](https://core.telegram.org/bots/api#update)
defines identity and event fields. [getWebhookInfo](https://core.telegram.org/bots/api#getwebhookinfo)
reports URL/status without reporting the configured secret. Checked 2026-10-05.
Quotas, outbox state machine, lease durations and internal routes are NexusCore
design choices. A public demo HTTPS endpoint, AgentHub consumer, valid live LLM
credentials and outgoing Telegram delivery still need separate verification.
