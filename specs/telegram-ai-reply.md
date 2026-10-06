# Telegram AI reply v1

Status: Approved by the user, 2026-10-06. Extends the approved integration
contracts and verified Telegram ingress; it is not implementation evidence.

## Goal and scope

One private text Telegram message produces one durable AgentHub job, a plain-text
AI answer and a Telegram delivery record. The user selected a first flow without
RAG or tools on 2026-10-06. Existing standalone APIs retain their contracts.
No document retrieval, semantic cache, tool execution, conversation-history
prompting, per-bot configuration UI, billing or deployment is included.

Observed prerequisites: AgentHub has synchronous LLM providers, SQLAlchemy,
Celery/Redis and legacy global records. Its Alembic directory is a placeholder;
startup currently uses create_all. Local uncommitted Groq support exists and the
AgentHub environment selects Groq. Preserve those changes, review/test the
relevant provider integration before including it, and exclude unrelated local
Compose changes. No secret value belongs in source, fixtures or this document.

## Demo provider and budget policy

The user requires no paid API usage. Only the existing Groq free account is
enabled for initial demo generation. OpenAI/Anthropic and other adapters remain
available to existing standalone callers but cannot be selected by platform jobs.
Disable fallback; never alter billing plans or purchase credits. Another locally
present credential does not authorize its use or prove free account access.
SDK brand names do not determine billing: the existing Groq adapter uses OpenAI's
compatible SDK against Groq's fixed endpoint.

Optional later providers: OpenRouter free catalog variants, Cloudflare Workers AI
on Workers Free and Gemini models on a verified Free Tier account. Each requires
user credentials and a verified account/model quota. Do not enable them merely
because an adapter exists. Quota exhaustion remains visible; no paid fallback.
Estimated list-price cost and actual demo billing are distinct.

Future UI token onboarding is planned separately: encrypted tenant-scoped
credentials, server-side provider/model validation, masked metadata and no token
readback. No UI or public credential-management API is added in this stage.

## Chosen approach

Reuse the signed ingress envelope and existing LLM provider abstraction. AgentHub
owns durable jobs/results/usage; WebHook Manager retains Telegram credentials
and owns sending. Both use PostgreSQL intents, fenced claims and independent
bounded scanners; Celery messages contain UUIDs only.

Rejected alternatives: synchronous LLM in intake delays Telegram acknowledgment
and loses recovery; Telegram credentials in AgentHub create an unnecessary
credential boundary. A single synchronous result callback does not protect
against worker or broker outages.

## Admission in AgentHub

Implement POST /internal/v1/telegram/updates with the exact existing deterministic
envelope and X-Webhook-Signature HMAC contract from telegram-ingress.md. Authenticate
before parsing; enforce a streamed 1 MiB limit, strict JSON/schema/UUID/time and
signed 64-bit identifiers. Reject duplicate JSON keys, non-finite numbers,
unexpected fields and mismatched idempotency_key. Error bodies never echo input.

Resolve canonical active bot/tenant through the existing WebHook Manager
GET /internal/v1/bots/{bot_id}/context using its pairwise service key; compare IDs.
No context or mismatched context means no work. Outage yields503 without admission.
No credentials are returned by context lookup. Never trust envelope tenant alone.

Persist one UUID job with its immutable envelope and digest. Unique event_id and
(bot_id, update_id) prevent duplicate jobs, including concurrent admission. First
admission returns202, an identical replay200, conflicting content409. Receipt is
exactly {event_id, job_id, state}; states pending/processing/completed/failed/unknown.
Completed means a durable AI result, not a confirmed Telegram answer. Commit
before queue submission; broker failure leaves a scanner-visible pending job.

## AI processing and uncertainty

Use an opt-in worker with explicit 25-second soft/30-second hard limits, a
60-second database-clock lease and fresh claim UUID. Every result update is fenced.
Recheck active context before the external operation. Persist provider/model
selection on the job before generation so later configuration cannot change it.
For the first live demo use the existing Groq provider with configured model;
controlled acceptance substitutes only its external HTTP boundary.

Perform one bounded generation, no provider fallback or hidden SDK retry, with
a 20-second request deadline and maximum1024 output tokens. Send one fixed system
instruction and the admitted question; no tools, retrieval, global cache or global
conversation lookup. Reuse existing provider interfaces through the smallest
compatible extension needed for platform timeout/token/retry options.

Persist an external-call-started marker before entering the provider call. Recover
an expired claim only if no call could have started. After call-started, a worker
crash, timeout, ambiguous provider error or failed persistence becomes unknown;
do not call the provider again automatically. Requeue safe pre-call context/network
failures at most5 times with min(2**attempt,60) seconds backoff. Explicit permanent
configuration/auth/validation failures are failed. Safe429 retries require evidence
that no generation occurred; otherwise choose unknown conservatively.

Atomically persist the returned answer, one scoped usage record and one reply
publication intent, then mark completed. Scope all records by tenant_id/bot_id;
use job_id for usage uniqueness. Require nonempty text, nonnegative finite usage
and a valid response. Empty output fails without a reply. Cost is provider-reported
tokens priced using existing estimates, not a guarantee of billed cost.
Trim answers over4096 characters to the first4095 plus an ellipsis. Preserve the
final text before any delivery attempt. A repeated completed job reuses it.

## Answer admission in WebHook Manager

Add signed POST /internal/v1/telegram/answers with an independent
AGENT_WEBHOOK_REPLY_KEY. The strict envelope carries UUID answer event_id,
event_type=telegram.answer.created, schema_version=1, UTC occurred_at, tenant_id,
bot_id, correlation_id, idempotency_key=telegram-answer:<ingress_event_id>, and
payload {ingress_event_id, job_id, text}. Never accept a caller-selected chat_id
or bot token. Signature and streaming/schema controls match ingress.

Resolve the original accepted ingress record by tenant/bot/ingress_event_id.
Require matching correlation identity and original publication job_id; if original
publication receipt is not yet persisted, return409 and defer the producer as a
documented readiness conflict. Derive chat_id from the stored normalized ingress.
Check fresh active context before accepting. Persist one answer/send intent per
ingress event atomically. Return202 first/200 identical replay with
{event_id, delivery_id, state}; conflicting content409. No sendMessage in this HTTP
handler. Result publisher retries transport/5xx/429/receipt ambiguity and the
documented not-ready409 with the same immutable identity, max10 attempts with
min(2**attempt,60) seconds backoff. Other400/401/403/404/409/415/422 are terminal.
Use a distinct static409 code to distinguish readiness from immutable conflict.

## Telegram sending

WebHook Manager claims a due send record with a fresh UUID and60-second lease,
checks active context, decrypts its own token and uses stored chat/text. Send
plain text through the existing bounded Telegram client with no parse_mode,
redirects, proxy inheritance or internal retry. Extend the client only as needed;
do not expose token-bearing URLs in logs/errors. Worker limits25/30 seconds,
HTTP total deadline20 seconds. Persist send-started before the call.

On confirmed success store Telegram message_id before succeeded. Explicit429
respects bounded retry_after up to3600 seconds; confirmed5xx rejection can retry,
max5 attempts. Explicit Telegram400/401/403 failures are terminal. Network timeout,
disconnect, malformed success or crash after send-started is unknown and must
not automatically resend. A scanner can recover pre-send claims; an expired
send-started claim becomes unknown. Bot deactivation prevents later claims.
There is no manual resend/reconciliation API in this implementation; inspect
unknown records before a separately authorized operator action.

## Schema and configuration

AgentHub: initialize Alembic with an explicit baseline matching current legacy
models and a forward platform migration; new scoped telegram_ai_jobs,
telegram_ai_usage and telegram_reply_outbox tables. Platform tables are excluded
from legacy create_all; platform mode requires migration head. Preserve standalone
startup. Do not stamp an existing database before checking its schema, and never
implicitly assign global data to a tenant. Legacy global APIs must not read the
new platform tables. Existing data is not altered or migrated automatically.

WebHook Manager: one new forward migration for telegram_answers/send intents,
with scoped indexes, local ingress FK, uniqueness and state/claim constraints.
No edit to already-applied migrations. All migration downgrade testing requires
explicit approval limited to separate newly created empty guarded test databases.

Opt-in settings in AgentHub: TELEGRAM_AI_ENABLED=false,
WEBHOOK_AGENT_INGRESS_KEY, WEBHOOK_INTERNAL_URL, WEBHOOK_AGENT_SERVICE_KEY,
AGENT_WEBHOOK_REPLY_KEY, platform provider/model and bounded limits. In WebHook
Manager: TELEGRAM_REPLIES_ENABLED=false and AGENT_WEBHOOK_REPLY_KEY. Reuse existing
credentials/configuration where appropriate. Root forwards pairwise keys, enables
dedicated worker/scanner profiles and does not supply Telegram encryption keys
to AgentHub. Validate URLs/secrets/bounds at enabled entrypoints; defaults remain
disabled. No new dependency is proposed: HTTP, ORM, queue and SDKs already exist.

## Verification and delivery

Close three increments independently: (1) real admission and durable recovery;
(2) controlled generation, result/usage and signed answer admission;
(3) controlled Telegram sending, then the specifically approved live demo.
Each increment includes relevant tests, lint/type checks, Docker/HTTP smoke and
fresh adversarial review/security pass before publishing current-task changes.

Use dedicated real PostgreSQL/Redis, separate databases and random namespaces.
Test malformed signatures/envelopes, cross-tenant pairs, inactive context/outage,
concurrent duplicate/conflict, SQL rollback, broker outage, duplicate tasks,
expired claims, stale fences, failure before/after external-call marker, empty
output, timeout/no automatic repeat, once-only usage/result, answer readiness,
canonical chat binding, Telegram429/permanent/ambiguous failures and deactivation.
Existing standalone suites and API smoke must stay green. Test full built-image
WebHook -> AgentHub -> reply admission -> controlled send path with recovery.

Live acceptance additionally requires a verified public HTTPS destination,
healthy migrated services and selected provider/model credentials. Present the
exact bot/destination and provisioning dry-run before requesting approval for
setWebhook. The human sends one private test message; observe original update,
job, result/usage and Telegram message identity without logging credentials or
personal message content. Never claim controlled HTTP testing proves live delivery.
