# NexusCore integration contracts v1

Status: Approved by the user on 2026-10-05. AuthFortress tenant foundation is
implemented; later integration stages remain planned. Created: 2026-10-04.
Local verification evidence: `docs/verification-tenants-2026-10-05.md`.

## Goal and first implementation boundary

A platform user authenticates through AuthFortress, creates a tenant, registers a
bot in that tenant, and receives an AI reply to a private Telegram text message.
The same user may belong to multiple tenants, and each tenant may own multiple
bots. Existing services remain independently runnable.

The first implementation is limited to AuthFortress tenant identity: models,
forward migration, create/list/read/authorize API and negative authorization
tests. Bot provisioning, queue recovery, AgentHub scoping and Telegram delivery
are later independently verified steps, not part of the first implementation.
Invitations, owner transfer, billing, media, groups, topics, edited messages,
dashboard, observability integration and deployment are outside v1 acceptance.

## Observed baseline before tenant implementation (2026-10-04)

| Service | Existing implementation | Integration gap |
|---|---|---|
| AuthFortress | UUID users; access JWT `sub`, `sid`, `type`, `exp`; existing `get_current_user` and sessions | No tenant/membership models |
| WebHook Manager | Local UUID users/API keys; owner-scoped sources; HMAC ingest; JSON delivery through Celery | AuthFortress JWT returns 401; Telegram token alone returns 401; concurrent dedup/recovery not proven |
| AgentHub | Integer conversation IDs; synchronous `/api/v1/query`; document embedding worker; global cache and usage | Telegram payload returns 422 without `question`; no tenant/bot scope |

Evidence: root `scripts/verify_stack.py`; AuthFortress `app/core/security.py`,
`app/models/user.py`, `app/services/jwt_service.py`; WebHook Manager
`src/services/event_service.py`, `src/infrastructure/queue/dispatcher.py` and
`src/infrastructure/queue/tasks/deliver_webhook.py`; AgentHub
`app/api/v1/query.py`, `app/models/conversation.py`, `app/cache/semantic_cache.py`.

## Identity ownership and authorization

AuthFortress owns tenants and memberships. WebHook Manager owns bot registrations,
their immutable tenant association and Telegram credentials. AgentHub owns scoped
AI resources and results. No cross-service database foreign keys or Python imports.

User access uses the existing AuthFortress access JWT. Tenant membership is checked
from the database on each request; no new tenant claims or changed login/refresh
response are required. Global `user/admin/superadmin` roles remain unchanged and
do not grant automatic access to other tenants.

Downstream user-facing platform APIs forward the access JWT to the AuthFortress
authorization endpoint over the configured internal HTTP URL. They never receive
the JWT signing secret. Callers select `tenant_id` in the resource path; it is a
selector, not authorization. A service fixes the permission for its route and
uses only the AuthFortress response as the user/tenant identity context.
An invalid/revoked JWT is 401; a valid identity without tenant visibility is 404;
an active member requesting an owner-only operation is 403. An unavailable
identity service yields 503 and no data access; positive authorization responses
are not cached in v1. Proposed client bounds: connect 2s, read 5s, no automatic
retry of user writes. No throughput or production availability SLA is asserted.

### First AuthFortress data model

- `Tenant`: UUID `id`, `name` (trimmed, 1..128 characters), UUID `created_by`
  referencing an existing user, `is_active` default true, UTC `created_at`.
  Names are display labels and need not be globally unique.
- `TenantMembership`: UUID `id`, UUID `tenant_id`, UUID `user_id`,
  `role` (`owner` or `member`), `is_active` default true, UTC `created_at`;
  unique `(tenant_id, user_id)`. Both references are local AuthFortress FKs.
- Create a tenant and its creator's active owner membership in one transaction;
  rollback leaves neither row. The owner is `created_by`; v1 does not transfer,
  deactivate or remove owners through a public API.
- The first API supports creator onboarding only. Member creation/invitations are
  a subsequent API task; fixture-created memberships exercise the role contract.

### First AuthFortress API

All routes reuse `get_current_user`, including current session and user checks.
Request bodies reject extra fields, especially caller-supplied owner or role.

| Method/path | Request | Success | Authorization |
|---|---|---|---|
| `POST /api/v1/tenants` | `{"name":"Example team"}` | 201 `TenantView` | Any active authenticated user; creator becomes owner |
| `GET /api/v1/tenants` | `offset=0`, `limit=50` (1..100) | 200 list of `TenantView`, ordered by `created_at,id` | Only active memberships in active tenants |
| `GET /api/v1/tenants/{tenant_id}` | UUID path | 200 `TenantView` | Active membership; missing/inaccessible/inactive tenant is 404 |
| `POST /api/v1/tenants/{tenant_id}/authorize` | `{"permission":"tenant.read"}` | 200 `AuthorizedContext` | Active membership and permission table below |

`TenantView` fields: `id` (UUID string), `name`, `role` (`owner`/`member`),
`created_at` (UTC RFC3339). Lists return `[]` for no memberships. Invalid body,
UUID, pagination or permission is 422. Auth failures preserve the existing
AuthFortress error conventions. A failed database transaction never returns 201.

`AuthorizedContext` fields: `user_id`, `tenant_id` (UUID strings), `role`,
`permission` (echoed validated permission), `allowed: true`. This response is
request-scoped information, not a transferable token or a service credential.

| Permission | Owner | Member |
|---|---|---|
| `tenant.read`, `bot.read`, `ai.read` | Allow | Allow |
| `tenant.manage`, `bot.manage`, `ai.configure` | Allow | Deny |

Bot/conversation/document ownership must also be checked by the resource-owning
service after tenant authorization. Permission alone does not establish ownership
of an arbitrary resource ID. Permission strings for later capabilities require
an explicit contract extension rather than accepting arbitrary strings.

## Bot context and service processing boundary

New platform bot routes belong in WebHook Manager under
`/api/v1/tenants/{tenant_id}/bots`; they use AuthFortress authorization and do not
create a second platform user. Existing standalone API-key/HMAC routes retain
their current contracts, but cannot substitute for platform authorization.

A bot registration binds one local UUID `bot_id` to one AuthFortress `tenant_id`
and verified numeric Telegram bot identity. Telegram identity is globally unique
among active platform registrations. The token is verified with `getMe` before
activation; no reassignment of an existing bot to another tenant in v1.
Webhook authentication uses a separately generated secret, and the receiving
route is `/webhooks/telegram/{bot_id}`. A route lookup supplies tenant identity;
neither Telegram JSON nor user-supplied headers can choose it.

Store Telegram tokens encrypted using an existing encryption library/secret
storage, with a configured external key; verify library availability in that
step. Never return tokens, put them in queue messages or log Telegram URLs.
Provisioning/setWebhook is an explicit operation, separate from API startup.

Service jobs are authorized as the registered bot, not as the Telegram sender or
as the platform user's expiring session. Telegram sender IDs are not AuthFortress
user IDs. Pairwise service credentials authenticate internal producer/consumer
routes; they never reuse `AUTH_SECRET_KEY` or accept user bearer tokens as service
credentials. Reuse existing outbound HMAC support for signed envelopes where
possible. Receiver checks the signature over raw bytes before parsing.

The AgentHub consumer must resolve active bot context through an authenticated
WebHook Manager internal lookup and compare canonical tenant/bot IDs before
processing. That lookup must establish active tenant status through AuthFortress.
No active context, timeout or mismatched pair means no processing. Delivery repeats
the active-context check before sending. Concrete bot/service provisioning APIs
and key configuration are a separate reviewed implementation spec.

## Update and answer envelope

Required fields: `event_id` (UUID), `event_type`, `schema_version` (integer 1),
`occurred_at` (ingress/answer creation time, UTC RFC3339), `tenant_id`, `bot_id`
(UUIDs), `correlation_id` (UUID), `idempotency_key` (nonempty string), `payload`
(object). Unsupported schema versions fail with 422. Envelope fields are strict;
unrelated optional Telegram fields in the raw Update may be ignored.

Example normalized ingress event, with fictional identifiers:

```json
{
  "event_id": "00000000-0000-4000-8000-000000000001",
  "event_type": "telegram.message.received",
  "schema_version": 1,
  "occurred_at": "2026-10-04T07:00:00Z",
  "tenant_id": "00000000-0000-4000-8000-000000000002",
  "bot_id": "00000000-0000-4000-8000-000000000003",
  "correlation_id": "00000000-0000-4000-8000-000000000004",
  "idempotency_key": "telegram:00000000-0000-4000-8000-000000000003:123",
  "payload": {
    "update_id": 123,
    "chat_id": 456,
    "message_id": 789,
    "question": "Hello"
  }
}
```

v1 processes only a new nonempty text `message` in a private chat. Use signed
64-bit Telegram identifiers; do not assume monotonically increasing update IDs.
Keep raw updates in scoped ingress storage, not in the normalized AI payload.
Valid unsupported update types are recorded as ignored and acknowledged without
LLM work. Payload fields are normalized from Telegram data, never accepted as an
alternative client-supplied AI/tenant context. Admission body limit is 1 MiB.

An answer envelope uses `event_type: ai.answer.ready`, a new `event_id`, the same
tenant/bot/correlation IDs, and `idempotency_key: answer:<ingress-event-id>`.
Its payload requires `in_reply_to` (ingress UUID), `answer` (nonempty string),
`tokens_used` (nonnegative integer), `cost_usd` (nonnegative decimal string),
`provider` and `model` (nonempty strings). Reply chat/message routing is resolved
from the original stored event, not chosen by the answer producer.

Add separate internal admission routes for normalized updates in AgentHub and
answers in WebHook Manager. Return 202 only after durable event/job persistence;
replay returns 200 with the original event/job identity and current state.
Conflicting content for one identity/key returns 409; unauthenticated internal
requests return 401; inactive/mismatched authorized context returns 403.
This preserves existing synchronous AgentHub `/api/v1/query` callers. Internal
admission performs no synchronous LLM call and queues work after durable admission.

## Idempotency and failure contract

- Unique ingress identity is `(bot_id, update_id)`, including concurrent requests.
  Different bots may share an update ID; replays reuse the original event and key.
- Ingress/event and publication intent commit atomically in PostgreSQL. Reuse
  Celery/Redis with a durable outbox and recovery; Redis alone is not the source
  of truth. Generic webhook delivery need not change in this first contract step.
- Atomically claim each admitted AI job. Persist one result and publication intent
  per ingress event. Completed replays reuse the result without another LLM call
  or usage entry. Scoped cache hits have zero incremental token/cost usage.
- Namespaces and every resource read/write/search/aggregate include authorized
  tenant scope and bot scope where applicable. Conversations are scoped to
  tenant/bot/private chat. Existing integer AgentHub IDs can remain integer IDs.
- Legacy global records receive no guessed tenant. They are inaccessible through
  platform routes until explicitly assigned through a reviewed migration procedure.
- At most one active Telegram send claim per answer. Persist successful Telegram
  message identity before finalizing. State distinguishes pending, processing,
  succeeded, failed and unknown outcomes.
- Confirmed transient failures use bounded retries/backoff, capped by configuration;
  Telegram 429 respects `retry_after`. Permanent validation/auth/permission errors
  are terminal. Bot deactivation prevents subsequent processing/delivery claims.
- A provider/send timeout or crash after a possible external side effect is
  `unknown`, not automatically retried. Resume/replay requires explicit operator
  reconciliation. Do not promise exactly one external charge/message when the
  external API does not offer the required idempotency guarantee.

Send plain text without `parse_mode` in the first flow. Persist the final reply
text before sending; cap it at 4096 characters, using the first 4095 and an
ellipsis if longer. Empty generation is terminal and creates no outgoing reply.

## Acceptance and ordered follow-up

1. **AuthFortress tenant foundation (implemented and verified):** tenant creation/list/
   read/authorize succeeds; two users cannot access each other's tenants by known
   UUID; owner/member permissions differ; one user may access two fixture-created
   memberships; global admin has no membership bypass; disabled membership/tenant
   and revoked session fail; request cannot assign owner/role; duplicate membership
   is rejected by PostgreSQL; creation rollback is atomic. Existing auth/RBAC tests
   remain green, Ruff/Mypy pass, new migration upgrades/downgrades/upgrades on an
   isolated disposable database. Root login smoke remains unchanged and passes.
   Expected files: AuthFortress `app/models/tenant.py`, `app/api/v1/tenants.py`,
   `app/api/v1/__init__.py`, a new `app/db/migrations/versions/004_*.py`, migration
   metadata registration as needed, `tests/test_tenants.py`, `docs/ERRORS.md` only
   if a reproduced existing bug is fixed, and API documentation.
2. **Bot admission:** review exact bot/service API, encrypted credentials and
   migration; verify Telegram-token auth, canonical context, concurrent duplicate
   handling and publish/recovery across broker outage with boundary doubles.
   Concrete first substep: [bot-registration.md](bot-registration.md), approved
   for implementation. AuthFortress service-status step is locally verified;
   registry/service context remains pending. Step 2b adds webhook
   provisioning, durable ingress/outbox and recovery before AgentHub consumption.
3. **AgentHub consumer:** scope storage/cache/retrieval/usage and migrate explicitly;
   verify forged tenant/bot pair rejection, cross-tenant conversation/document/cache
   isolation, concurrent worker claims, result replay and provider unknown outcome.
4. **Answer delivery:** reviewed internal answer route/outbox/send claim; verify
   unknown send outcomes, disabled bots, duplicate answers, 429 and terminal errors.
5. **Acceptance flow:** controlled Telegram/provider boundaries first, then an
   explicitly authorized live check with real bot/provider credentials.

Each stage requires its own narrow tests and relevant service regression checks,
forward migrations and disposable roundtrip when schema changes. No public
deployment gate is satisfied by local successful boundary doubles.

## Choices, risks and review questions

Online AuthFortress authorization is selected to preserve session revocation and
current membership without distributing signing keys or changing token format.
Locally trusting JWT tenant claims requires new issuance/revocation/JWKS behavior;
trusting a caller's tenant selector alone violates the project invariant.

Assumptions for review: creator is the sole initial owner; member is read-only;
v1 handles private text and a single plain-text reply; uncertain external side
effects require operator handling. No additional dependency is proposed for the
first AuthFortress implementation. Later service authentication/provisioning details
require their own concrete specification before code changes.

Primary risks: identity-service outage denies access (bounded timeout, fail closed);
legacy/global data needs explicit assignment (no implicit backfill); queue/external
ambiguity can lose or duplicate effects (outbox/claims/unknown state); unscoped legacy
APIs remain unsuitable for public shared deployment (keep isolated until scoped).

## Telegram references

- [Update identity](https://core.telegram.org/bots/api#update): repeated/out-of-order
  updates and identifiers after inactivity.
- [Webhook authentication and retries](https://core.telegram.org/bots/api#setwebhook):
  secret-token header, optional update filtering and retries after non-2xx responses.
- [Plain-text delivery](https://core.telegram.org/bots/api#sendmessage): text length,
  returned message and optional formatting.
- [Retry delay](https://core.telegram.org/bots/api#responseparameters): `retry_after`.

References checked on 2026-10-04. Timeouts, ownership policy and unknown-outcome
handling above are NexusCore design choices, not Telegram guarantees.
