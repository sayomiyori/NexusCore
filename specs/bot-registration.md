# Bot registration and service context v1

Status: Approved for implementation. Date: 2026-10-05.
Implementation proceeds in the ordered acceptance steps below; approval does not
establish that bot registration or downstream enforcement works.
Step 1 is implemented and locally verified in AuthFortress: 190 tests passed,
Ruff/Mypy, Docker build and HTTP service-status checks passed on 2026-10-05.
Step 2 clients/config and root Compose key forwarding are implemented and locally
verified: 136 WebHook Manager tests passed (69 focused), Ruff/strict Mypy, Docker
build and standalone HTTP/worker smoke passed; independent client review approved.
Bot registry/API, context endpoint and atomic registration quota are implemented.
Local acceptance: 162 tests, 84.56% coverage, Ruff/strict Mypy, independent
read-only review, isolated migration upgrade/down/upgrade/check and real HTTP
AuthFortress JWT -> WebHook -> live Telegram getMe passed. Credentials are
encrypted in PostgreSQL; tenant/RBAC/session failure paths deny access.
Evidence: docs/verification-bot-registry-2026-10-05.md (local-only).
Webhook provisioning, ingress/outbox, AI and Telegram answers remain unimplemented.
Parent contract: [integration-contracts.md](integration-contracts.md).

## Goal and implementation boundary

A tenant owner registers a Telegram bot using an AuthFortress access session.
WebHook Manager verifies its Telegram identity, stores credentials encrypted and
provides tenant-scoped management and authenticated service context. Members can
read registrations; only owners can register or deactivate them.

This is step 2a of bot admission. Step 2b implements Telegram webhook provisioning,
ingress normalization, durable admission/outbox and recovery before any AI
consumer is connected. A registration alone does not receive or process updates.
Token rotation, reactivation, transfer, deletion, invitations, AI work and outgoing
Telegram messages require subsequent contracts.

## Inspected baseline before implementation

- WebHook Manager `src/api/v1/dependencies/auth.py` authenticates standalone
  API keys and local users. Platform routes need a separate AuthFortress dependency.
- Existing routers use async services and repositories, domain errors and
  `CursorPage` pagination; keep these conventions.
- `src/core/config.py`, `src/core/dependencies.py`, `src/api/main.py` and Alembic
  metadata registration are the integration points. Current migration head is
  `e6e39a93b58d`; existing migrations must not be edited.
- `httpx` and `python-jose[cryptography]` are already declared. Local imports show
  httpx 0.28.1 and cryptography 50.0.2. No new dependency is proposed.
- AuthFortress already provides tenant authorization but no credential-authenticated
  tenant status endpoint for service jobs.
- User changes in WebHook Manager `docker-compose.yml` and untracked `.cursor/`
  predate this task and must be preserved.

## User authorization

Each platform request forwards its bearer access token to the configured
AuthFortress `POST /api/v1/tenants/{tenant_id}/authorize`. The route fixes the
permission; request bodies cannot select identity, tenant or permission.

Validate a 200 response as `user_id`/`tenant_id` UUIDs, owner/member role,
the exact requested permission and literal `allowed: true`; its tenant must
match the requested path. Invalid JSON, mismatched context or unexpected status
fails closed with 503. Preserve issuer 401/403/404 as generic local responses.
No local JWT verification, signing-key sharing, new local platform user or
positive authorization cache is introduced.

AuthFortress calls use connect 2s, read/write/pool 5s, TLS verification,
no redirects and no automatic retries. Its configured base URL has no userinfo,
query or fragment. HTTP is allowed only for the documented isolated local network;
deployment outside that network requires HTTPS. No URL comes from a user request.
Inactive user/session/membership/tenant and global-role bypass behavior continues
to come from AuthFortress. Writes reauthorize after Telegram verification and
before persistence; authorization and the local commit are not a distributed
transaction, so no atomic cross-service revocation guarantee is asserted.

## Public management API

Base path: `/api/v1/tenants/{tenant_id}/bots`. UUID path parameters.

| Method/suffix | Request | Permission | Success |
| --- | --- | --- | --- |
| POST base | `BotCreate` | `bot.manage` | 201 `BotView` |
| GET base | `cursor` UUID or absent, `limit` 1..100, default 50 | `bot.read` | 200 `CursorPage[BotView]` |
| GET `/{bot_id}` | No body | `bot.read` | 200 `BotView` |
| POST `/{bot_id}/deactivate` | No body | `bot.manage` | 200 `BotView` with `is_active: false` |

`BotCreate` is exactly `{ "name": "Support", "token": "<supplied privately>" }`.
Name is a strict string trimmed to 1..128 characters. Token is a secret string,
1..256 ASCII characters, numeric prefix, colon and nonempty suffix containing
only letters, digits, `_` or `-`. Reject unexpected fields and bodies above 4 KiB.
No token value, ciphertext or request input is included in validation errors;
invalid bot requests return 422 with `{ "detail": "Invalid bot request" }`.
Path/query validation errors are likewise sanitized for these routes.

`BotView`: `id`, `tenant_id` UUIDs; `name`; `telegram_bot_id` integer; `username`
string or null; `is_active` boolean; UTC RFC3339 `created_at`, `updated_at`;
`webhook_status: "not_configured"` in this step. It excludes credentials and
issuer user/session data. Returning a registration does not configure a webhook.

List/read include inactive registrations for an authorized tenant. Query both
tenant and bot identity for resource access, before mutation; a bot belonging to
another tenant and a missing bot both return 404. Lists order by UUID ascending,
reuse the existing cursor envelope and return an empty list for no registrations.
An unknown cursor is only a UUID ordering boundary, never an ownership lookup.
Repeated deactivation returns the same inactive registration without side effects.

Errors: 401 missing/invalid/revoked bearer; 403 insufficient member permission;
404 hidden tenant/bot; 409 duplicate Telegram identity; 422 invalid request;
429 local registration admission exceeded; 400 rejected Telegram credential;
503 missing feature configuration, issuer/provider outage or invalid provider data.
Error bodies are static local messages; no remote description, token or URL:

| Status | Public management response |
| --- | --- |
| 400 | `{ "detail": "Invalid Telegram token" }` |
| 401 | `{ "detail": "Not authenticated" }`, with bearer challenge |
| 403 | `{ "error": "forbidden" }` |
| 404 | `{ "error": "not_found" }` |
| 409 | `{ "error": "conflict" }` |
| 422 | `{ "detail": "Invalid bot request" }` |
| 429 | `{ "error": "rate_limited" }` |
| 503 | `{ "detail": "Service unavailable" }` |

## Telegram verification and registration transaction

Use an async HTTP client with a fixed `https://api.telegram.org` origin and only
`GET /bot<validated-token>/getMe`. No user-defined host, redirects, environment
proxy inheritance or alternate Bot API server. Connect timeout 2s; other timeouts
5s; responses capped at 64 KiB. No automatic retry in the first implementation.
Use HTTP boundary doubles in automated tests, not a configurable production URL.

Require HTTP 200, JSON object, literal `ok: true`, object `result`, positive signed
64-bit integer `id` (not a boolean), literal `is_bot: true`, and optional string
`username` of at most 128 characters. Ignore unrelated provider fields. Username
is nullable: Telegram documents it as optional. Bot identity comes from this
response, not from request fields or the token's numeric prefix.

Well-formed Telegram errors with error_code 401/404 map to generic 400. Telegram
429/5xx, timeouts, TLS/transport errors, malformed/oversized replies or unexpected
profile data map to generic 503. No row is created on verification failure.

After initial authorization, atomically admit at most 10 registration attempts in
a trailing 60-second sliding window per `(user_id, tenant_id)` through the existing
Redis client. One Lua operation uses Redis TIME in milliseconds, removes scores
at or before `now - 60000`, counts admissions, and adds a fresh UUID member only
if below quota, then sets a 60-second expiry. Each admitted request counts even
if provider verification fails; denied requests do not extend the window. Scores
at exactly the trailing boundary expire; simultaneous timestamps remain distinct.
Do not key on credentials. Denied requests perform no Telegram call;
Redis outage fails closed with 503. Limits are configurable, positive and not an SLA.

Verify Telegram, reauthorize, allocate bot UUID, encrypt its bound credential
payload, then insert and commit once. Duplicate insert races are decided by a
PostgreSQL unique constraint, rolled back and returned as 409. Retrying POST after
a lost 201 may return 409; it does not rotate credentials or create another row.
An authenticated owner can resolve the existing row through the tenant list.
No Celery event, setWebhook call or Telegram message occurs in this transaction.

## Persistence and credential protection

New WebHook Manager `telegram_bots` table:

| Field | Storage/invariant |
| --- | --- |
| `id` | UUID primary key |
| `tenant_id` | UUID, required; no cross-service FK |
| `created_by` | AuthFortress user UUID, required; no legacy local-user FK |
| `name` | VARCHAR(128), required |
| `telegram_bot_id` | BIGINT, positive; named global UNIQUE constraint |
| `username` | VARCHAR(128), nullable |
| `credentials_encrypted` | TEXT, required; never serialized as a response |
| `is_active` | BOOLEAN, required, default/server default true |
| `created_at`, `updated_at` | TIMESTAMPTZ, required, server initial defaults |

Index `(tenant_id, id)` supports scoped cursor queries. `updated_at` changes on
the first deactivation; repeated deactivation leaves it unchanged. Persist no
webhook readiness flag yet; `webhook_status` is a literal API capability marker.

V1 keeps Telegram identity unique across both active and inactive registrations.
This intentionally reserves the identity after deactivation because transfer and
reactivation are excluded. It satisfies active uniqueness and prevents obtaining
a new tenant association through deactivate/register. Existing rows never move.

Use existing cryptography Fernet with an external generated key. Encrypt JSON
containing `bot_id`, `tenant_id` and token together; verify IDs against the canonical
row on decryption to detect swapped ciphertexts. Decrypt only inside the provider
operation that needs it. Do not return credentials through service context either.
Decryption or bound-payload validation failure returns generic 503 and performs
no provider call; ciphertext must not be overwritten as automatic recovery.
Do not derive this key from JWT/service/HMAC secrets. Losing the key prevents
credential recovery; retain it separately from database backups. Key rotation is
a subsequent operator procedure, not an automatic destructive rewrite.

Credential protection includes HTTPX/HTTPCore request logging (Telegram URLs carry
tokens), exceptions, traceback causes, validation `input`, request body/header
capture and Sentry breadcrumbs/events. Redact or suppress sensitive provider
telemetry even in DEBUG; normal middleware logs only method/path/status/actor ID.
Tests inspect both success and failure logging/response paths using fictional tokens.

The new forward migration follows `e6e39a93b58d`, adds only this table/constraints/
index and registers metadata. Do not backfill or attach legacy sources, users,
events or endpoints to guessed tenants. Down/up verification uses a newly created
empty isolated database, with database and row-count guards and explicit approval.

## Service authorization and canonical bot context

Service calls authenticate using `X-Service-Key`, never user bearer JWTs. Keys
are independent per edge, random with at least 32 bytes, outside URL/query/body,
compared in constant time. A missing/wrong service key is 401; missing configured
key is 503. Keys use ASCII; reject malformed or oversized incoming values (maximum
256 bytes) with 401. Compare byte values so non-ASCII input cannot trigger a
comparison 500. No service credential grants user-management or bot-registration rights.
Service headers and credentials must not appear in access logs or telemetry.
Invalid service credentials return `{ "detail": "Invalid service key" }`.
Service configuration/upstream failures return the generic 503 body above.

1. AuthFortress: `GET /internal/v1/tenants/{tenant_id}/status`, requiring
   `AUTHFORTRESS_WEBHOOK_SERVICE_KEY`. Return 200
   `{ "tenant_id": "<canonical UUID>", "is_active": true }` for an active tenant;
   missing/inactive tenant returns 404. Do not accept a user token as a substitute.
   Its 404 body is `{ "detail": "Tenant not found" }` for both cases.
   The authenticated caller receives only tenant status, no users or memberships.
2. WebHook Manager: `GET /internal/v1/bots/{bot_id}/context`, requiring
   `WEBHOOK_AGENT_CONTEXT_KEY`. Resolve the registration's stored tenant, then
   call the AuthFortress service status endpoint. Return 200
   `{ "bot_id": "<UUID>", "tenant_id": "<UUID>", "telegram_bot_id": 123,
   "is_active": true }` only if both bot and tenant are active. Missing bot: 404;
   inactive bot/tenant: 403; issuer/key configuration failures, timeout, invalid
   response or unexpected status: 503. Validate canonical tenant in its reply.
   Specifically, AuthFortress status 404 maps to context 403; issuer 401/403
   indicates service credential/configuration failure and maps to 503.
   Context 403/404 use the same domain-error bodies as public bot routes.
   Re-read the bot's active state after the issuer call to catch deactivation
   during that call; later processing still requires its own fresh claim checks.

Context cannot select a tenant, return a Telegram token or act as a transferable
authorization token. No positive cache. Later consumers compare both canonical
IDs to their envelope and perform this check before processing/delivery claims.
Current service context reports registration eligibility, not webhook readiness.
It does not dispatch jobs; consumers and envelope admission remain later steps.
Service calls use the same bounded issuer timeouts; no automatic retry here.

## Configuration and compatibility

| Variable | Used by | Default/behavior |
| --- | --- | --- |
| `PLATFORM_BOTS_ENABLED` | WebHook Manager | false; new routes disabled with 503 |
| `AUTHFORTRESS_BASE_URL` | WebHook Manager | unset; fixed trusted issuer URL when enabled |
| `BOT_CREDENTIALS_KEY` | WebHook Manager | unset; valid Fernet key required when enabled |
| `AUTHFORTRESS_WEBHOOK_SERVICE_KEY` | AuthFortress + WebHook Manager | unset; same edge key on both |
| `WEBHOOK_AGENT_CONTEXT_KEY` | WebHook Manager; later AgentHub | unset; separate context-read key |
| `RATE_LIMIT_BOT_REGISTER` | WebHook Manager | 10 per 60s, positive integer |

When enabled, missing/malformed required configuration fails startup with sanitized
validation errors. When disabled, existing standalone startup/API behavior remains
valid; new routes fail closed. Invalid configured service keys are rejected even if
the feature is disabled. AuthFortress service endpoint is unavailable until its
edge key is configured. No key reuses existing auth or delivery secrets.
Update service and root `.env.example` only with safe placeholders and document
explicit opt-in. Compose forwards issuer URL/service names and the appropriate
keys per service; credentials are not embedded into command arguments or URLs.

## Ordered implementation and acceptance

1. AuthFortress service tenant-status route/config: real database verifies active,
   inactive, nonexistent tenant; missing/wrong key, user JWT substitution and
   unavailable config fail. Existing tenant/auth/RBAC suite, Ruff/Mypy pass.
2. WebHook issuer/provider clients/config: HTTP doubles prove 200, issuer
   401/403/404, timeouts, redirect refusal, schema/context mismatch, provider
   credential errors, 429/5xx and malformed/oversized responses. Prove no secret
   appears in response/validation errors/logging/telemetry.
3. Bot model/repository/service/API and forward migration: real PostgreSQL verifies
   create/list/read/deactivate, owner/member permissions, tenant A versus tenant B
   reads/deactivation, known forged bot/tenant IDs, revoked session, input injection,
   inactive records, deterministic cursors, two tenant memberships and DB rollback.
   Concurrent duplicate registrations yield one 201 and one 409 with one row;
   deactivated identities cannot be moved/re-registered. Ciphertext is not plaintext,
   decrypts under the configured key and rejects a swapped bound payload.
4. Service context: correct independent edge credentials allow reads only; wrong
   service/user keys, inactive bot/tenant, mismatched issuer tenant and outages
   deny processing. No credential retrieval or positive-cache path.
5. Atomic registration admission tests: quota cannot be exceeded concurrently;
   duplicate timestamps cannot collapse attempts; trailing-window boundary expiry
   is tested without sleeps; Redis outage prevents provider
   calls. Existing WebHook tests, Ruff and strict Mypy pass. Fresh migrations
   upgrade/check/down/up/check with explicit approval pass; previous tables remain.
6. Local HTTP smoke: existing root auth/transport smoke stays green; real
   AuthFortress JWT authorization reaches the new WebHook routes. Controlled
   Telegram boundary verifies registry/context behavior without changing a real
   bot's webhook. Live getMe requires a privately supplied demo token; live
   setWebhook is outside this implementation.

Expected paths: WebHook `src/api/v1/{dependencies,schemas,routers}` for bot routes;
`src/services/bot_service.py`, `src/infrastructure/db/{models,repositories}` for
the bot and existing metadata/migration wiring; small provider/issuer HTTP client
modules, config/DI/main/logging, focused tests and README/.env.example.
AuthFortress internal router, config/router registration, focused tests and
README/.env.example. Root Compose/.env.example and status documents only as needed;
preserve pre-existing sibling Compose edits.

## Decisions and risks for review

No blocking product question is inferred from the approved parent contract.
Review choices: reserve deactivated identities; no credential rotation/reactivation
in this step; feature opt-in; separate service status read; registration quota 10/min.
The new AuthFortress internal interface is a deliberate contract extension.

Issuer outages deny access; bound calls and fail closed. Local tenant UUIDs have no
cross-service FK; validate user/service contexts on each operation. Ciphertext key
loss prevents recovery; retain keys securely. Permanent identity reservation limits
re-onboarding until a reviewed rotation/reactivation contract. Provider verification
is not Telegram webhook provisioning; complete admission and outbox separately.

Online issuer authorization preserves current sessions/memberships without local
JWT/JWKS redesign. Reusing standalone API-key users would create a second platform
identity; attaching bots to legacy source-owner UUIDs would require an unjustified
mapping/backfill. Use the existing layering and clients, not a new service.

## Primary references checked on 2026-10-05

- [Telegram getMe](https://core.telegram.org/bots/api#getme): token verification
  returns a User; [User](https://core.telegram.org/bots/api#user) documents optional
  username and the need for 64-bit identifiers.
- [Telegram setWebhook](https://core.telegram.org/bots/api#setwebhook): future
  explicit provisioning and the separate secret-token header; not a registration
  side effect.
- [cryptography Fernet](https://cryptography.io/en/latest/fernet/): authenticated
  credential encryption and key handling; consulted through Context7.

Timeouts, admission quota, authorization endpoints and inactive-identity reservation
are NexusCore design choices, not Telegram guarantees.
