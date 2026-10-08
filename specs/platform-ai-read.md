# Tenant-scoped AI read API

Status: implementation scope selected under the user's 2026-10-08 instruction
to continue the project stages. No deployment or provider access is required.

## Contract

AgentHub adds opt-in `PLATFORM_READ_ENABLED=false` and a fixed internal
`AUTHFORTRESS_BASE_URL`. Reads do not enable AI processing. Every request forwards
exactly one bearer to AuthFortress's existing tenant authorize route for `ai.read`,
then resolves fresh active bot context through the existing WebHook client and
compares tenant/bot identifiers. No cached authorization or local JWT decoding.
Owner and member are allowed; invalid/revoked identity is 401, inaccessible scope
is 404, unavailable/malformed upstream authorization is 503. Disabled routes are
404. No database query follows a failed authorization.

- `GET /api/v1/tenants/{tenant_id}/bots/{bot_id}/ai/jobs`: optional UUID `cursor`,
  `limit` default 50, range 1..100; ascending UUID keyset order; returns `items`
  and `next_cursor`. Items contain id, event_id, state, attempts, provider, model,
  created_at, updated_at only. No message/answer text, envelope, chat IDs or claims.
- `GET /api/v1/tenants/{tenant_id}/bots/{bot_id}/ai/usage`: required timezone-aware
  `start` and `end`; `start < end`, at most 31 days; inclusive start, exclusive end.
  Returns completed usage record count, input/output tokens and decimal-string
  `estimated_cost_usd`. Empty scope returns zeros. Estimates are not billing.

All SQL filters tenant and bot together. Reuse the existing platform tables and
indexes; no migration, legacy data reassignment or access to global usage tables.
Legacy APIs remain unchanged and must stay private. Startup requires existing
platform migration head when reads or AI are enabled. No new dependencies.

## Acceptance

Verify with isolated PostgreSQL and controlled issuer/context HTTP: owner/member,
cross-tenant and cross-bot records, empty scope, pagination, time boundaries,
validation, disabled mode, missing/duplicate/invalid/revoked bearer, inactive
context, issuer outage/redirect/oversize/malformed/mismatched receipt. Error and
success bodies must not expose credentials or private message content. Run the
existing regression, lint/type checks and fresh adversarial/security review.

This step does not implement tenant RAG/cache/configuration, dashboard UI,
observability integration, public deployment or real provider calls.

## Verification on 2026-10-08

AgentHub's full suite passed 228 tests with isolated PostgreSQL/Redis. Focused
read/startup acceptance passed 70 tests both on the host and in an image built
on the previously verified runtime dependencies. Ruff and the expanded CI Mypy
scope passed. Fresh read-only adversarial/security review approved the change;
its focused Bandit check passed. No new dependencies or schema changes.

Commands (AgentHub virtualenv; test database variables must point to disposable
storage, with platform database name `nexus_agent_ai_*_test`):

```powershell
python -m alembic upgrade head
python -m pytest tests/ -q
python -m pytest tests/test_platform_reads.py tests/test_platform_schema.py -q
python -m ruff check .
python -m mypy app/platform app/api/v1/platform_reads.py
```

Root `docker compose --profile telegram-ai config --quiet` passed. Built-image
HTTP acceptance used the real local issuer and bot registry with a separate AI
test database: owner jobs/usage 200, no bearer 401, foreign tenant/bot 404, and
the same bearer after logout 401. Temporary APIs were removed; no Telegram or
LLM call was made. The root image override now pins the tested patch image;
platform reads and AI processing remain disabled. Fresh dependency resolution,
public deployment and long-running load were not verified in this increment.
