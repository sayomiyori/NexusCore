# Root Telegram end-to-end integration

Status: proposal for review, 2026-11-11. Documentation only: no code, Compose,
migration or runtime change is part of this file.

Base: `origin/main` at `25e3083f2ebff097b53bb55e2075de75b1dbf7f6`.

This is a separately requested roadmap artifact. It does not change the current
AuthFortress priority in `AGENTS.md`, does not activate any root profile or
platform flag, and does not authorize a rollout or a live Telegram/provider
run. Every slice below requires explicit approval and its own recorded
evidence before any runtime change.

## Status vocabulary

- **Implemented** — the behaviour exists in a repository. It is not
  automatically active in the root stack.
- **Verified** — implemented and covered by the recorded isolated acceptance
  named in this document. This is not root or production verification.
- **Planned** — agreed design, no implementation in the target repository yet.
- **Blocked** — cannot be completed without a missing credential, contract or
  decision. Do not present a blocked item as ready.

## Summary

- The three gaps recorded in the root README are design boundaries of the
  standalone route, not missing service features. The root end-to-end flow
  closes them by adopting the implemented opt-in platform route; the standalone
  contracts stay unchanged and keep their current 401/401/422 boundary checks.
- The platform chain (bot registration through AuthFortress, Telegram
  secret-token intake, signed internal admission, scoped generation, signed
  answer publication, Telegram send) is **Implemented + Verified in isolated
  acceptance** in the sibling repositories and in the root-level controlled
  fixture `scripts/verify_telegram_ai.py`. One guarded live demo passed on
  2026-10-08. None of that ran against the actual root `docker-compose.yml`
  topology with platform modes enabled.
- What remains at the root: a wiring regression gate for the root Compose
  environment, a controlled end-to-end acceptance derived from the actual root
  Compose file, and an activation runbook with a status closure. These are the
  three slices in §9.
- Live activation, public deployment and capacity remain excluded (§10).

## 1. Goal and boundary

The root Telegram end-to-end (E2E) flow is: one private text Telegram message
is admitted by the root `webhook_service`, normalized and durably published to
the root `agent_service`, answered by one bounded generation, and the answer is
delivered back to the original Telegram chat by the root send worker — with
AuthFortress identity and tenant scope enforced at every hop:

```text
Telegram → webhook_service /webhooks/telegram/{bot_id}
         → outbox → agent_service /internal/v1/telegram/updates (signed)
         → scoped job → answer → webhook_service /internal/v1/telegram/answers (signed)
         → send worker → Telegram sendMessage
```

This document defines the integration architecture only: the decision per
observed gap, the exact hop contracts, identity/idempotency/security/retry
rules, and three root-repository implementation slices. It does not modify any
service source, schema, Compose file or runtime configuration.

## 2. Current baseline

### 2.1 Implemented and verified platform chain

| Area | State | Evidence |
| --- | --- | --- |
| Tenant identity, membership, `authorize` API | **Implemented + Verified** in AuthFortress; used by every platform hop | [integration-contracts.md](integration-contracts.md), AuthFortress tenant tests |
| Bot registration, encrypted credentials, service context | **Implemented + Verified** in WebHook Manager | [bot-registration.md](bot-registration.md) |
| Webhook provisioning (dry-run/apply, `replace_url`) | **Implemented + Verified** | [telegram-ingress.md](telegram-ingress.md) |
| Telegram intake `/webhooks/telegram/{bot_id}` | **Implemented + Verified** | [telegram-ingress.md](telegram-ingress.md) |
| Signed admission `POST /internal/v1/telegram/updates` | **Implemented + Verified** in AgentHub | [telegram-ai-reply.md](telegram-ai-reply.md), AgentHub README |
| Scoped generation, usage, answer publication | **Implemented + Verified** in AgentHub | [telegram-ai-reply.md](telegram-ai-reply.md) |
| Answer admission + Telegram send worker | **Implemented + Verified** in WebHook Manager | [telegram-ai-reply.md](telegram-ai-reply.md), WebHook Manager README |
| Root Compose flag/key forwarding, `telegram-ingress`/`telegram-ai` profiles | **Implemented**, config-level only; no regression test covers the wiring matrix | [docker-compose.yml](../docker-compose.yml), [.env.example](../.env.example) |
| Controlled E2E fixture `scripts/verify_telegram_ai.py` | **Implemented + Verified**; hand-built fixture environment, not derived from the root Compose file | [isolated-smoke.md](../docs/isolated-smoke.md) |
| Root stack running platform modes | **Not exercised**; the 2026-10-13 local release kept platform modes and live traffic disabled | [README.md](../README.md) |
| E2E activation runbook (one document) | **Not written**; the procedure is spread across three specs and the demo-edge doc | See §9, Slice 3 |

### 2.2 The three observed gaps

The standalone route of the root smoke reproduces the gaps recorded in the
README. Reproduction points are in `scripts/verify_stack.py`:

| Gap | Standalone route behaviour | Reproduced by |
| --- | --- | --- |
| 1 — identity | WebHook Manager requires its own API key; an AuthFortress bearer JWT gets 401 | `verify_stack.py` "auth contracts" stage: `GET /api/v1/auth/keys` with an AuthFortress bearer returns 401 |
| 2 — intake | Signed ingress requires `X-Webhook-Signature` HMAC; Telegram's `X-Telegram-Bot-Api-Secret-Token` header alone returns 401 | `verify_stack.py` "webhook contracts" stage: posting to `/webhooks/ingest/{slug}` with only the secret-token header returns 401 |
| 3 — answer shape and return path | Delivery preserves the Telegram JSON fields; AgentHub `/api/v1/query` requires `question` and returns 422; nothing sends a generated answer back to Telegram | `verify_stack.py` final check: `POST /api/v1/query` with the Telegram payload returns 422; the delivery engine posts to the subscribed callback endpoint, not to the original chat |

These checks are correct assertions of the standalone boundary. They stay in
the smoke unchanged; closing the gaps means routing the E2E flow through the
platform contracts below, not weakening them.

## 3. Decisions per gap

### 3.1 Gap 1 — platform identity (AuthFortress JWT vs WebHook API key)

**Decision.** The root E2E authenticates the platform user through AuthFortress
and uses WebHook Manager's opt-in platform bot routes
(`/api/v1/tenants/{tenant_id}/bots...`) with `PLATFORM_BOTS_ENABLED=true`.
Every platform request forwards the bearer access token to AuthFortress
`POST /api/v1/tenants/{tenant_id}/authorize`; the tenant in the path is a
selector, never the authorization source. The standalone API-key routes keep
their contracts unchanged.

**Justification.** AuthFortress is the single identity layer (repo
`AGENTS.md`); online authorization preserves session revocation and current
membership without distributing signing keys; tenant scope is enforced on
every read/write; no second user store is created. This is exactly the
identity model the approved [integration-contracts.md](integration-contracts.md)
specifies.

**Rejected alternatives.**

- *Provision a WebHook standalone API key for the root flow.* Keeps the
  identity outside AuthFortress, carries no tenant scope, and produces a
  shared long-lived secret. `integration-contracts.md` explicitly states
  standalone API-key routes cannot substitute platform authorization.
- *Teach standalone `/api/v1/*` routes to validate AuthFortress JWTs.* Violates
  the "standalone routes retain their current contracts" boundary, duplicates
  the issuer-authorization client outside the platform layer, and mixes local
  UUID users with AuthFortress users in one route family. Standalone-only
  deployments have no issuer at all.
- *Use a service key end-to-end.* Owner-only operations (bot registration,
  webhook provisioning) need a human owner identity for quota, audit and
  ownership; a service key cannot carry tenant membership.

### 3.2 Gap 2 — Telegram intake (secret token vs HMAC)

**Decision.** Telegram terminates on the platform admission route
`POST /webhooks/telegram/{bot_id}`, authenticated by exactly one
`X-Telegram-Bot-Api-Secret-Token` header checked against the per-bot stored
SHA256 digest in constant time; the route lookup supplies `tenant_id`. The
HMAC-signed `/webhooks/ingest/{source_slug}` stays standalone-only. The
internal WebHook → AgentHub hop keeps its own HMAC
(`X-Webhook-Signature: sha256=<hex>` signed with `WEBHOOK_AGENT_INGRESS_KEY`) —
a different hop with a different key.

**Justification.** Telegram's webhook contract offers only the secret-token
header; it cannot produce our HMAC. The platform route was designed and
verified for exactly this header, and binds authentication to a registered bot
and its immutable tenant association. HMAC stays where both ends hold the key:
machine-to-machine hops.

**Rejected alternatives.**

- *Accept the Telegram secret-token on `/webhooks/ingest/{slug}`.* The
  standalone route is keyed by source slug, has no per-bot secret store and no
  tenant binding; accepting the header there would require teaching it a bot
  identity it does not own and would conflate external intake with the internal
  signed transport.
- *Have the edge or Telegram compute the HMAC.* Telegram cannot; the demo edge
  would need to hold per-bot secrets to sign on Telegram's behalf, which is
  precisely the platform route's job — an extra secret holder for no gain.
- *Disable HMAC verification on the signed ingress for the root.* Removes
  integrity from the internal transport. Rejected outright.

### 3.3 Gap 3 — AI request shape and the missing return path

**Decision.** The root E2E does not use `/api/v1/query`. WebHook Manager
normalizes the admitted message into the v1 envelope (`payload.question`) at
ingress time and durably publishes it to AgentHub's signed
`POST /internal/v1/telegram/updates`. AgentHub processes one durable
tenant/bot-scoped job and publishes the answer to WebHook Manager's signed
`POST /internal/v1/telegram/answers`; the send worker delivers it to the
original chat with `sendMessage`. The 422 for a raw Telegram payload on
`/api/v1/query` stays as correct documented behaviour.

**Justification.** Internal admission is asynchronous and durable — no
synchronous LLM call inside intake or delivery (`integration-contracts.md`).
The job is scoped by tenant/bot, idempotent and recoverable. The answer
producer never selects a destination: chat routing is resolved from the stored
normalized ingress. The integrated root runs AgentHub with
`PLATFORM_TENANT_ENABLED=true`, which closes `/api/v1/query` entirely
([platform-agent-boundary.md](platform-agent-boundary.md)), so the standalone
query route is structurally unavailable to the root E2E anyway.

**Rejected alternatives.**

- *Map the Telegram payload to `{question}` and deliver it to `/api/v1/query`
  through the legacy subscription engine.* Synchronous LLM inside the delivery
  task; global/unscoped records; no durable job, recovery or usage scoping; no
  return path (the delivery engine posts to configured endpoints, not to the
  original chat); and the route is closed in the integrated root.
- *Extend `/api/v1/query` to accept Telegram updates.* Pollutes the standalone
  contract, still has no tenant/bot scope or durable job, and still has no
  send-back path.
- *Let AgentHub send the Telegram reply directly.* Violates the credential
  boundary: AgentHub receives no Telegram credentials
  (`BOT_CREDENTIALS_KEY` never reaches any AgentHub process); WebHook Manager
  owns sending.

## 4. Hop contracts

Status codes and bodies below are the implemented service contracts; the
slices in §9 verify them against the root wiring, they do not change them.
Error bodies are static; no remote description, token or URL is echoed.

### 4.1 Platform user and tenant (AuthFortress)

Standard AuthFortress login issues the access JWT. Tenant creation and
authorization follow [integration-contracts.md](integration-contracts.md):
`POST /api/v1/tenants` (201 `TenantView`), and downstream services forward the
bearer to `POST /api/v1/tenants/{tenant_id}/authorize` (200 `AuthorizedContext`
with `user_id`, `tenant_id`, `role`, `permission`, `allowed: true`). Invalid or
revoked JWT → 401; valid identity without tenant visibility → 404; member
requesting an owner-only operation → 403; issuer outage → 503 with no data
access. Positive authorization responses are not cached.

### 4.2 Bot registration and webhook provisioning (WebHook Manager)

`POST /api/v1/tenants/{tenant_id}/bots` with exactly
`{"name": "...", "token": "<private>"}` → 201 `BotView` (`id`, `tenant_id`,
`name`, `telegram_bot_id`, `username`, `is_active`, `created_at`,
`updated_at`, `webhook_status`). Errors: 400 invalid Telegram token, 401, 403
member, 404 hidden tenant/bot, 409 duplicate Telegram identity, 422 sanitized
invalid request, 429 registration quota (default 10 per 60 s per
`(user_id, tenant_id)`), 503 configuration/issuer/provider outage. The token is
verified with `getMe` before persistence and stored Fernet-encrypted, bound to
bot and tenant UUIDs.

Webhook provisioning is owner-only
`POST /api/v1/tenants/{tenant_id}/bots/{bot_id}/webhook` with a strict body
`{"dry_run": true|false}` and optional strict boolean `replace_url` (default
false). Dry run returns 200 with `{bot_id, tenant_id, webhook_url, operation:
"setWebhook", dry_run: true}` and performs no external call or state write.
Apply returns 200 with `{bot_id, tenant_id, webhook_url, webhook_status}`.
`webhook_status` is one of `not_configured`, `configuring`, `configured`,
`failed`, `unknown`. Concurrent setup claims return 409 (60-second database
claim); an already configured identical target is a no-op; retry reuses exactly
the same URL and secret. A failed setup blocks intake with 403 until retried.
The response never contains a token, secret or ciphertext.

### 4.3 Telegram intake — `POST /webhooks/telegram/{bot_id}`

Preconditions, checked before payload parsing: feature enablement (disabled
route → 503), bot lookup by `{bot_id}` (unknown → 404), exactly one
`X-Telegram-Bot-Api-Secret-Token` header (missing/wrong/repeated → static 401;
ASCII URL-safe, 1..256 bytes; SHA256 digest compared in constant time),
prepared secret (unprepared → 403), fresh active bot and tenant status through
AuthFortress (inactive → 403; issuer outage → 503).

Body: streamed, at most 1 MiB (above → 413 without buffering the remainder),
`application/json` (parameters allowed; unsupported type/encoding → 415),
UTF-8 JSON object, no duplicate keys, NaN or infinities (malformed → sanitized
422). Strict signed 64-bit identifiers; `update_id` required; no monotonicity
assumption. Only a new nonempty text `message` in a private chat is processed;
structurally valid other updates are persisted as ignored and acknowledged.

Responses: first supported admission 202 `{"status": "accepted", "event_id"}`;
ignored 200 `{"status": "ignored", "event_id"}`; replay of the same canonical
content 200 `{"status": "duplicate", "event_id"}` with the original
`event_id`; changed content for the same `(bot_id, update_id)` → static 409;
failed insert/commit → static 503 with no partial record. These acknowledge
local durability only.

### 4.4 Signed internal admission — `POST /internal/v1/telegram/updates`

WebHook Manager serializes the immutable v1 envelope to deterministic UTF-8
bytes and signs it as `X-Webhook-Signature: sha256=<hex>` with
`WEBHOOK_AGENT_INGRESS_KEY`. AgentHub verifies the signature over the raw
bytes before parsing; a missing/invalid signature → 401. Envelope fields
(strict, no unexpected fields): `event_id` (UUID, server-generated),
`event_type` `telegram.message.received`, `schema_version` `1` (unsupported →
422), `occurred_at` (UTC RFC3339), `tenant_id`, `bot_id` (UUIDs),
`correlation_id` (UUID), `idempotency_key` `telegram:<bot_id>:<update_id>`,
`payload` `{update_id, chat_id, message_id, question}` (normalized from
Telegram data; raw Telegram metadata and credentials are never included).
Streamed 1 MiB cap and strict JSON rules match intake.

AgentHub resolves canonical active bot/tenant context through WebHook Manager
`GET /internal/v1/bots/{bot_id}/context` (pairwise service key
`WEBHOOK_AGENT_SERVICE_KEY`, matching WebHook's `WEBHOOK_AGENT_CONTEXT_KEY`)
and compares both IDs with the envelope before processing. No context or a
mismatched pair → no work; context outage → 503 without admission; inactive
context → 403.

Responses: first durable admission 202 with exactly
`{"event_id", "job_id", "state"}` where state is one of `pending`,
`processing`, `completed`, `failed`, `unknown`; identical replay 200 with the
same identities; conflicting content for one identity/key → 409. `completed`
means a durable AI result, not a sent Telegram answer. The commit precedes the
best-effort UUID queue notification, so a broker outage still returns the
durable receipt.

### 4.5 Scoped generation

The generation worker claims one due job with a fresh UUID and a 60-second
database-clock lease; every result update is fenced. Active context and
generation configuration are rechecked before a committed call-started
marker. One bounded provider call (20-second deadline, no SDK retries,
`max_completion_tokens` 1024, fixed system prompt plus the admitted question;
no tools, retrieval, history or cache). Pre-call context/network failures retry
at most 5 times with `min(2**attempt, 60)` seconds backoff; after the
call-started marker, a crash, timeout or ambiguous provider error is `unknown`
and is never automatically retried. Confirmed permanent
configuration/auth/validation failures and empty output are `failed` and
create no outgoing reply. The result, one scoped usage record and one reply
publication intent commit atomically. Stored text is capped at 4096 characters
(4095 plus an ellipsis).

### 4.6 Signed answer admission — `POST /internal/v1/telegram/answers`

AgentHub publishes the immutable answer envelope, signed with the independent
`AGENT_WEBHOOK_REPLY_KEY`, verified by WebHook Manager over raw bytes before
parsing. Envelope: new UUID answer `event_id`, `event_type`
`telegram.answer.created`, `schema_version` `1`, UTC `occurred_at`,
`tenant_id`, `bot_id`, the same `correlation_id` as the ingress event,
`idempotency_key` `telegram-answer:<ingress_event_id>`, and `payload`
`{ingress_event_id, job_id, text}`. A caller-supplied `chat_id` or bot token is
never accepted.

WebHook Manager resolves the original accepted ingress record by
tenant/bot/`ingress_event_id`, requires the matching correlation identity and
the persisted publication `job_id`, derives `chat_id` from the stored
normalized ingress, and rechecks fresh active context even on identical
replays. If the original publication receipt is not yet persisted, it returns
409 with `detail=ingress_publication_not_ready` (retryable by the producer
with the same immutable identity); immutable content/identity conflict returns
the distinct terminal 409 `detail=answer_conflict`.

Responses: first admission 202 `{"event_id", "delivery_id", "state"}`;
identical replay 200 with the same identities; 401 unauthenticated; 422
sanitized validation errors. No `sendMessage` runs in this HTTP handler.

### 4.7 Telegram send

The send worker claims a due send intent with a fresh UUID and a 60-second
lease, rechecks active context, decrypts its own bot credential and uses only
the stored chat/text. `sendMessage` is plain text with no `parse_mode`,
redirects, inherited proxies or transport retries; 20-second total deadline;
25-second soft / 30-second hard worker limits. A send-started marker commits
before the external call. On confirmed success the Telegram `message_id` is
persisted before `succeeded`. Explicit 429 respects bounded `retry_after`
(capped at 3600 seconds); confirmed 5xx rejection retries at most 5 attempts;
confirmed 400/401/403 are terminal. Network timeout, disconnect, malformed
success or a crash after send-started is `unknown` and never automatically
resent; only expired pre-send claims recover. There is no manual resend API.

### 4.8 Backward compatibility

- Standalone WebHook routes (`/api/v1/auth/*`, `/api/v1/endpoints`,
  `/api/v1/subscriptions`, `/api/v1/deliveries/*`,
  `/webhooks/ingest/{slug}`) and the legacy delivery/recovery engine keep
  their contracts. The root smoke's gap checks (401 bearer, 401 secret-token,
  422 query) remain valid assertions.
- AgentHub standalone routes (`/api/v1/query`, `/api/v1/documents`,
  `/api/v1/conversations`, `/api/v1/usage`) keep their contracts for
  standalone deployments. In the integrated root they are closed by
  `PLATFORM_TENANT_ENABLED` ([platform-agent-boundary.md](platform-agent-boundary.md)).
- Existing callers, databases and the 2026-10-13 pinned local release require
  no migration or restart from this document. Platform tables need the forward
  service migrations already defined in the service specs; no existing database
  is stamped or backfilled, and legacy NULL-tenant rows receive no guessed
  tenant.
- The E2E is additive opt-in: every platform flag defaults to `false`; a root
  stack that does not enable them behaves exactly as today.

## 5. Identity, tenancy and idempotency

| Concern | Rule |
| --- | --- |
| `tenant_id` authority | Route lookup (`/webhooks/telegram/{bot_id}`) or the authenticated `/internal/v1/bots/{bot_id}/context` response. A `tenant_id` from a request body, query or envelope is only compared, never trusted; a mismatch fails closed. The path tenant on user routes is a selector — AuthFortress `authorize` is the authorization. |
| `bot_id` authority | Path parameter bound to the registered bot; the envelope `bot_id` must match the canonical context. A bot of another tenant is 404, not 403, to avoid existence disclosure. |
| `correlation_id` | Server-generated UUID on the ingress event; the answer envelope carries the same value; it links hops but is not unique and is not an idempotency key. |
| Ingress idempotency | Unique `(bot_id, update_id)` in PostgreSQL, including concurrent admission; different bots may share an `update_id`. Envelope key `telegram:<bot_id>:<update_id>`. |
| Admission idempotency | Unique `event_id` and `(bot_id, update_id)` prevent duplicate jobs; identical replay returns the original `{event_id, job_id, state}`; conflicting content for one identity is 409. |
| Answer idempotency | One answer/send intent per ingress event; key `telegram-answer:<ingress_event_id>`; identical replay is 200 with the original identity; content conflict is the terminal `answer_conflict` 409. |
| Send idempotency | At most one active Telegram send claim per answer; the persisted Telegram `message_id` finalizes the outcome; a repeated completed job reuses the stored result without another generation or usage entry. |

Duplicate versus conflict is uniform across hops: the same canonical content
under one identity returns the original receipt (200); changed content under
one identity fails with 409. Queue messages carry only UUIDs; PostgreSQL is
the source of truth for state.

Recorded divergence: `integration-contracts.md` §"Update and answer envelope"
proposed `event_type: ai.answer.ready` with
`idempotency_key: answer:<ingress-event-id>`. The implemented and verified
contract ([telegram-ai-reply.md](telegram-ai-reply.md), both service READMEs)
uses `telegram.answer.created` with `telegram-answer:<ingress_event_id>`. This
spec treats the implemented form as authoritative. Renaming either value would
be a breaking change requiring a new `schema_version` and a coordinated
producer/consumer update; it is not part of any slice here.

## 6. Security

### 6.1 Telegram secret token

One independent 32-byte URL-safe secret per bot, generated at initial setup,
Fernet-encrypted (payload bound to tenant and bot), stored as SHA256 for
verification. Intake requires exactly one `X-Telegram-Bot-Api-Secret-Token`
header (ASCII URL-safe, 1..256 bytes) and compares its digest in constant
time. No positive authentication cache. The secret is never returned by any
API, never placed in queue messages or logs, and the API never logs Telegram
URLs. Intake keeps authenticating the preserved secret while provisioning is
`configuring`/`unknown`; a definite setup failure blocks intake with 403 until
retried. `getWebhookInfo` cannot prove secret installation.

### 6.2 HMAC and service keys

Each internal hop is signed over raw bytes before parsing:
`X-Webhook-Signature: sha256=<hex>`. Pairwise keys are independent random
ASCII secrets of 32..256 bytes: `WEBHOOK_AGENT_INGRESS_KEY` (WebHook → AgentHub
admission), `AGENT_WEBHOOK_REPLY_KEY` (AgentHub → WebHook answers), and the
context pair `WEBHOOK_AGENT_CONTEXT_KEY` = `WEBHOOK_AGENT_SERVICE_KEY`
(Authenticated `X-Service-Key` context lookup, compared in constant time).
No key reuses `AUTH_SECRET_KEY`, `WEBHOOK_SECRET_KEY`, the Fernet
`BOT_CREDENTIALS_KEY` or another edge's key. Service keys never appear in
URLs, bodies, access logs or telemetry; a missing/wrong key is 401; missing
configuration is 503. Credential separation in the root wiring: no AgentHub
process receives `BOT_CREDENTIALS_KEY`; no recovery/publication/scanner
process receives `GROQ_API_KEY`.

### 6.3 Replay and duplication

Deterministic identities make replays safe: re-delivered Telegram updates,
re-sent admission envelopes and re-published answers all resolve to the
original durable record and return 200 with the original identity, producing
no second job, usage entry or send. Concurrent duplicates are serialized by
PostgreSQL uniqueness (one winner, others replay). Changed content under one
identity is rejected with 409. Bounded inactivity, 1 MiB streamed caps and
strict JSON parsing bound every admission surface.

### 6.4 Timing and oracle resistance

Constant-time comparisons for the secret digest, HMAC and service keys.
Static, sanitized error bodies — no remote provider text, no token echoes, no
existence disclosure across tenants (404 for foreign tenant/bot). Response
bodies are bounded (64 KiB internal identity receipts; Telegram replies).
Registration is rate-limited per `(user_id, tenant_id)`. Telegram platform
HTTP logging is suppressed because URLs carry tokens; Sentry excludes local
variables, request bodies/headers/cookies/query, HTTP breadcrumbs and Telegram
events in platform mode.

### 6.5 Key rotation

Current state — **no automatic rotation exists anywhere in the chain**, and
this spec adds none:

| Secret | Replacement procedure today | Constraint |
| --- | --- | --- |
| Telegram webhook secret | v1 has no rotation; `replace_url` preserves the encrypted secret, and a retry reuses the same secret/URL | Rotating requires a new secret plus a live `setWebhook` — a separately authorized live operation |
| Pairwise service keys (`ingress`, `reply`, `context`) | Coordinated `.env` change on both ends and a restart of the affected processes | Single-key verifiers: an unsynchronized change produces a 401 storm on the internal hops |
| `BOT_CREDENTIALS_KEY` (Fernet) | Operator procedure, not an automatic rewrite; ciphertext is never overwritten as recovery | Loss prevents credential recovery; retain separately from database backups |
| AuthFortress JWT signing key | Out of scope; AuthFortress contract | — |

Rejected: silent or automatic rotation. Internal receivers verify one key per
edge, so a rolling change cannot be atomic across processes, and the Telegram
secret change is a live external mutation. A future rotation contract requires
a dual-key acceptance window (old and new accepted during rollout), staged
restart ordering, per-bot re-provisioning through the existing provisioning
route, and negative tests proving the old key stops working after cutover.
That contract is follow-up work and is not authorized by this document.

## 7. Retry, backoff and failure classes

Transient failures retry with bounded backoff; permanent failures are
terminal; ambiguous outcomes after a possible external side effect are
`unknown` and never retried automatically. PostgreSQL `next_attempt_at` is
authoritative; workers have no internal retry loops; claims use 60-second
database-clock leases and fenced updates.

| Hop | Transient (retry) | Permanent (terminal) | Unknown (no auto retry) |
| --- | --- | --- | --- |
| Publication to AgentHub admission | Network timeout, 429 (respect `retry_after` ≤ 3600 s), 5xx, invalid/oversized/redirect replies, lost receipt; backoff `min(2**attempt, 60)` s; bounded by `PLATFORM_PUBLICATION_MAX_ATTEMPTS` (default 10, range 1..100) | 400/401/403/404/409/415/422 from the receiver | Final expired claim without a persisted result → `failed` with static `admission_outcome_unconfirmed` (does not assert the remote never accepted) |
| Generation | Pre-call context/network failures, ≤ 5 attempts, backoff `min(2**attempt, 60)` s; 429 only with evidence no generation occurred | Confirmed permanent config/auth/validation failure, empty output | Crash/timeout/ambiguous error after the committed call-started marker |
| Answer publication to WebHook | Transport/5xx/429/receipt ambiguity and the readiness 409 `ingress_publication_not_ready`; same immutable identity; ≤ 10 attempts; backoff ≤ 60 s | Authentication/content rejection and the conflict 409 `answer_conflict` | Expired publication claim after a possible remote acceptance |
| Telegram `sendMessage` | Explicit 429 with bounded `retry_after` ≤ 3600 s; confirmed 5xx, ≤ 5 attempts | Confirmed 400/401/403 | Timeout, disconnect, malformed success, crash or expired claim after send-started |

Duplicates: every hop's unique identity plus 200-replay semantics mean bounded
retries cannot create a second job, usage record, answer or send. The
controlled acceptance deliberately loses one admission receipt and re-delivers
updates to prove this.

Lost answer: a generation or send that reached `unknown` requires explicit
operator reconciliation; there is no manual resend API and no automatic second
generation. Bot deactivation prevents new processing and delivery claims at
every hop. No exactly-once guarantee is claimed for external effects; the
supported guarantee is at-least-once delivery with idempotent admission and
deduplicated outcomes.

## 8. Failure scenarios relevant to the root flow

| Scenario | Expected behaviour | Data effect |
| --- | --- | --- |
| Redis/Celery down when Telegram posts | Intake still commits ingress + outbox (202), scanner recovers after broker restart | No loss at admission; publication deferred |
| AgentHub admission endpoint down | Outbox retries within the attempt limit; exhaustion → `failed`/`admission_outcome_unconfirmed` | Update stored, job may or may not exist remotely; operator reconciles |
| Groq timeout after call-started | Job → `unknown`; no automatic second generation | Possible external charge without a stored answer; usage may be unrecorded |
| Answer admission 409 readiness | Producer retries the same immutable envelope | Answer eventually admitted once; no duplicate send intent |
| `sendMessage` timeout after send-started | Send intent → `unknown`; never auto-resent | Telegram may hold a delivered message; operator inspects before any approved action |
| Same Telegram update delivered twice (Telegram retry) | Second admission 200 duplicate with the original `event_id` | One job, one usage, one send |
| Deactivated bot receives a message | Intake 403; no new claims at any hop | Stored history preserved |
| Foreign tenant attempts bot read/provisioning | 404 (hidden) / 403 (permission) | No existence disclosure |

## 9. Implementation slices

Three ordered root-repository slices. Each is a separate reviewed change with
its own evidence; a later slice does not start because an earlier one "looks
fine". Sibling repositories are not modified by any slice. No slice enables any
flag on the adopted local root stack or performs a live Telegram/provider call.

### Slice 1 — Root platform wiring regression gate

**Closes the wiring half of gaps 1 and 2** (the configuration that makes the
platform route usable in the root stack).

**Problem.** The root `docker-compose.yml`/`.env.example` platform wiring is
config-reviewed only. The controlled E2E fixture builds its environment by
hand (`verify_telegram_ai.ai_config()`), so a wiring drift — a pairwise key
forwarded to the wrong process, a flag hardcoded `true`, `BOT_CREDENTIALS_KEY`
reaching an AgentHub process, a scanner receiving `GROQ_API_KEY` — would pass
every existing check while breaking or weakening the real stack.

**Scope and files.** One new root test
`tests/test_verify_root_telegram_wiring.py`, parsing `docker-compose.yml` and
`.env.example` directly (same approach as
`tests/test_verify_platform_agent_boundary.py`; no Docker engine needed).
Asserts at minimum:

- every platform flag (`PLATFORM_BOTS_ENABLED`, `PLATFORM_TELEGRAM_ENABLED`,
  `TELEGRAM_AI_ENABLED`, `TELEGRAM_REPLIES_ENABLED`, `PLATFORM_READ_ENABLED`)
  defaults to `false` in `.env.example` and in the Compose defaults;
- `BOT_CREDENTIALS_KEY` is forwarded only to WebHook processes that decrypt
  (`webhook_service`, `webhook_sender`) and to no `agent_*` process;
- `GROQ_API_KEY` is emptied on every AgentHub recovery/publication/scanner
  process, and `TELEGRAM_AI_MODEL`/provider settings reach only generation
  processes;
- the pairwise key matrix: `WEBHOOK_AGENT_INGRESS_KEY` on WebHook publication
  processes and AgentHub admission processes; `WEBHOOK_AGENT_CONTEXT_KEY`
  (WebHook) mirrored as `WEBHOOK_AGENT_SERVICE_KEY` (AgentHub);
  `AGENT_WEBHOOK_REPLY_KEY` on WebHook answer admission/sender and AgentHub
  publication; `AUTHFORTRESS_WEBHOOK_SERVICE_KEY` on both issuer and WebHook
  processes;
- `TELEGRAM_WEBHOOK_ORIGIN` is forwarded to `webhook_service` and
  `webhook_sender`;
- `webhook_worker`/`webhook_outbox_recovery` keep platform API flags `false`
  (route-serving flags stay on the API), and the `telegram-ingress`/
  `telegram-ai` profiles contain exactly the documented scanner/worker
  services;
- every published port remains bound to `127.0.0.1`;
- `agent_service` keeps the platform preflight command and its healthcheck
  (does not regress [platform-agent-boundary.md](platform-agent-boundary.md)).

**Order.** First: pure static gate, no Docker, defines the wiring contract the
later slices derive from. If the test finds a real wiring bug, the fix is a
separate reviewed change; the test records the finding, it does not silently
fix it.

**Acceptance commands.**

```powershell
$py = 'D:\Programming\NexusCore\.venv\tooling-checks\Scripts\python.exe'
& $py -m unittest tests.test_verify_root_telegram_wiring -v
& $py -m unittest discover -s tests -p 'test_verify*.py' -q
& $py -m ruff check --no-cache scripts tests
& $py -m compileall -q scripts tests
```

**Definition of done.** The new test passes and the full discovered root suite,
Ruff and compilation stay green; every assertion above fails closed on drift;
no runtime change; the slice status is recorded in the README verification
section.

### Slice 2 — Root-derived controlled E2E acceptance

**Closes gaps 1–3 against the actual root topology.**

**Problem.** The E2E chain has never run through the root Compose wiring. The
existing `scripts/verify_telegram_ai.py` proves the service contracts in a
hand-built fixture; it cannot detect that the root `docker-compose.yml`
itself miswires the platform route.

**Scope and files.** One new root driver
`scripts/verify_root_telegram_e2e.py` (reusing `verify_stack` /
`verify_telegram_ai` helpers), plus `tests/test_verify_root_telegram_e2e.py`
(unit-level checks of the derivation), `docs/isolated-smoke.md` (commands and
receipt contract) and `README.md` (status). The driver:

1. renders the actual root Compose with
   `docker compose --profile telegram-ingress --profile telegram-ai config
   --format json`, supplying the required `${:?...}` variables and pairwise
   keys from a synthetic temporary env file (never the root `.env`);
2. transforms the rendered config into an owned fixture: cached pinned images
   instead of `build`, no `container_name`, no host ports, fixture
   database/Redis URLs, verification-script mounts and controlled-boundary
   command overrides for the services that need the synthetic Telegram/Groq
   interception — the **environment per service is taken from the rendered
   root Compose**, so the wiring under test is the real one;
3. enables only the fixture platform flags (synthetic values flow through the
   same variables the root forwards) and runs the full chain: real issuer
   login → tenant creation → bot registration with an AuthFortress bearer
   (gap 1 closed) → provisioning dry-run/apply → Telegram-shaped update
   admitted with the secret-token header (gap 2 closed) → signed admission
   receipt → controlled generation → signed answer admission → canonical
   `sendMessage` payload recorded by the controlled Telegram boundary
   (gap 3 closed);
4. keeps the existing duplicate/conflict, lost-receipt, broker/postgres outage
   and deactivation gates, and re-asserts the Slice 1 key matrix against the
   resolved environment at runtime.

Boundaries stay controlled: no real Telegram, no real Groq, no root `.env`, no
host ports, owned `nexus-smoke-<uuid>` project, stopped owned containers,
credential-free receipt (same ownership rules as `verify_telegram_ai.py`).

**Order.** Second; depends on Slice 1 (the static gate defines the wiring
contract this slice exercises). If deriving the fixture from the rendered
Compose proves impractical in review, the recorded fallback is to keep the
hand-built fixture but add a strict comparison of its service environments
against the rendered root Compose environment matrix — derivation remains the
preferred design because it exercises the real topology end to end.

**Acceptance commands.**

```powershell
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_root_telegram_e2e.py
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_root_telegram_e2e.py --scanners
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_stack.py
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_telegram_ai.py --scanners
```

The last two commands prove the standalone gap checks and the existing
controlled fixture remain unchanged. Root regressions, Ruff and compilation
run as in Slice 1.

**Definition of done.** The new driver exits 0 with a receipt recording the
root-derived topology (`docker compose config` source hash), the three gap
closures (bearer accepted on platform routes; secret-token admission 202;
canonical send payload observed), the recovery/duplicate gates, and
`external_calls_enabled=false`; the standalone smoke still reproduces the three
documented gap checks; no sibling repository or root runtime change.

### Slice 3 — Activation runbook and status closure

**Documents how a future, separately approved live activation would use the
closed gaps. The activation itself is not part of this or any slice.**

**Problem.** The live-activation procedure is spread across
[telegram-ingress.md](telegram-ingress.md), [telegram-ai-reply.md](telegram-ai-reply.md)
and [docs/telegram-demo.md](../docs/telegram-demo.md); the README records the
three gaps without a closure path; there is no single rollback story.

**Scope and files.** One new document
`docs/root-telegram-e2e-activation.md` and a README update:

- runbook: preconditions (Slice 1+2 evidence accepted; verified public HTTPS
  origin via the optional demo edge; fresh or rehearsed root stack; operator
  key checklist from `.env.example`), ordered steps (enable keys → flags →
  profiles → bot registration → provisioning dry-run reviewed → approved
  `setWebhook` apply → one human private test message → observe the four
  durable receipts), rollback (flags off, edge stopped, no volume deletion,
  Telegram webhook left installed requires its own reviewed operation), and
  the never-do list (no automatic resend of `unknown` outcomes; no stamping of
  existing databases; no quota exhaustion fallback to paid inference);
- README: replace the open-ended three-gap paragraph with the closure status
  (gaps closed by the platform route; standalone boundary checks retained),
  link this spec and the runbook, and update the "Next work" item 1 to point
  at the runbook gate.

**Order.** Last; requires Slice 1 and Slice 2 acceptance evidence to be
recorded first.

**Acceptance commands.**

```powershell
docker compose -f docker-compose.yml -f docker-compose.telegram-demo.yml `
  --profile telegram-ingress --profile telegram-ai config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Invalid E2E demo Compose configuration' }

$py = 'D:\Programming\NexusCore\.venv\tooling-checks\Scripts\python.exe'
& $py -m unittest discover -s tests -p 'test_verify*.py' -q
& $py -m ruff check --no-cache scripts tests
```

The Compose command validates the documented composition only, with values
from the operator environment and without printing resolved secrets; it starts
nothing.

**Definition of done.** The runbook and README are committed, reviewed and
internally consistent with the service specs; statuses use the
Implemented/Verified/Planned/Blocked vocabulary; no runtime change; the
document states explicitly that live activation requires its own approval and
is outside this spec.

## 10. What is explicitly NOT included

- **No public deployment.** No VPS, TLS certificate, domain, DNS or reverse
  proxy decision; the optional demo edge remains temporary preparation
  infrastructure ([docs/telegram-demo.md](../docs/telegram-demo.md)).
- **No live activation.** No `setWebhook` apply, no real Telegram traffic, no
  real provider inference, no platform flag enabled on the adopted local root
  stack, and no change to the 2026-10-13 pinned local release. The slices run
  only in owned isolated fixtures.
- **No capacity or load certification.** The existing bounded load probes are
  health/readiness measurements, not production capacity
  ([specs/isolated-load-smoke.md](isolated-load-smoke.md)).
- **No changes to standalone contracts or service source.** AuthFortress,
  WebHook Manager and AgentHub repositories are untouched by the slices; the
  standalone 401/401/422 boundary checks stay.
- **No key rotation mechanism** (§6.5 records the follow-up requirements
  only).
- **No RAG, tools, conversation history, semantic cache, media, groups,
  topics, edited messages or formatted replies** in the E2E flow; one
  plain-text private message and one plain-text answer.
- **No EventPipe/PipeWatch event wiring** for the Telegram flow; that is the
  separate [root-observability-integration.md](root-observability-integration.md)
  roadmap.
- **No new services, ports, dependencies or queues.**
- **No exactly-once guarantee** for external effects; no billing, quota or
  tenant-invitation features beyond the existing registration rate limit.
- **No multi-tenant UI/dashboard work**; dashboard reads remain their own
  specs.

## 11. Blockers and open questions

No blocker prevents the design or the slices. Recorded notes:

1. **Envelope naming divergence** (§5): the parent contract's
   `ai.answer.ready`/`answer:` naming versus the implemented
   `telegram.answer.created`/`telegram-answer:`. Resolved by treating the
   implemented, verified contract as authoritative; a cleanup would be a
   breaking schema change and is not proposed here.
2. **Key rotation contract** (§6.5): designed requirements recorded; needs its
   own spec and dual-key acceptance before implementation.
3. **Slice 2 derivation complexity**: rendering and transforming the root
   Compose is new engineering; the recorded fallback (environment-matrix
   comparison against the hand-built fixture) keeps the slice deliverable if
   derivation is rejected in review.

## 12. Review references

- [README request flow, verification status and next work](../README.md)
- [Integration contracts](integration-contracts.md)
- [Bot registration and service context](bot-registration.md)
- [Telegram webhook admission and durable publication](telegram-ingress.md)
- [Telegram AI reply](telegram-ai-reply.md)
- [Integrated AgentHub tenant boundary](platform-agent-boundary.md)
- [Isolated smoke and scanner acceptance](../docs/isolated-smoke.md)
- [Telegram demo edge](../docs/telegram-demo.md)
- [WebHook Manager repository](https://github.com/sayomiyori/WebHook_Manager)
  and its README (standalone routes, platform bot/Telegram routes, answer
  admission, durable sending)
- [AgentHub repository](https://github.com/sayomiyori/AgentHub) and its README
  (standalone API, signed admission checkpoint, bounded generation, answer
  publication)
- Root smoke drivers: [`scripts/verify_stack.py`](../scripts/verify_stack.py),
  [`scripts/verify_telegram_ai.py`](../scripts/verify_telegram_ai.py)

References checked on 2026-11-11. Retry bounds, lease durations, quotas and
internal route names are NexusCore design choices recorded from the approved
specs and the implemented services, not Telegram guarantees.
