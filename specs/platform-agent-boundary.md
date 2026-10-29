# Integrated AgentHub tenant boundary

AgentHub's standalone API is intentionally unauthenticated and serves legacy
NULL-tenant documents, conversations, usage and LLM queries. The NexusCore root
must not expose that mode on its loopback port or the shared `nexus_net` bridge.

## Required configuration

`docker-compose.yml` runs `agent_service` through
`scripts/agent_platform_preflight.py`, then starts uvicorn only when
`PLATFORM_TENANT_ENABLED=true` is supported and active. The variable defaults to
`true`; `.env.example` records the secure default.

The preflight fails closed when the AgentHub revision does not expose
`tenant_enabled` (for example, an old checkout) or when an operator explicitly
disables it. In that case the API container exits instead of silently serving
the legacy routes.

The container healthcheck runs `scripts/agent_platform_healthcheck.py`. It is
healthy only when `/health` is 200 and `/api/v1/documents`, `/metrics` and
`/mcp/sse` all return 404. A host override that replaces the preflight command
but keeps the healthcheck therefore becomes unhealthy instead of silently
reopening the standalone API.

## Version and schema pairing

The preflight proves that the AgentHub revision recognises the flag. It does not
prove the database schema head; AgentHub's lifespan requires the head named by
that revision's `PLATFORM_REVISION`:

| Source | Expected AgentHub head |
|---|---|
| Current local build context / pinned local image | `003_tenant_resources` |
| `origin/main` `11352ff` (unified release) | `004_merge_ai_resources` |

These are not interchangeable. Building `11352ff` against a `003` database
requires a reviewed forward migration to `004` before the API can start. The
current dirty worktree also lacks the `ai_settings` router that `11352ff` has;
do not describe it as equivalent. A mismatch fails closed at lifespan and is an
outage, not an open legacy API.

## Boundary

With the flag active, AgentHub closes the untenant routes
`/api/v1/documents`, `/api/v1/query`, `/api/v1/conversations` and
`/api/v1/usage`, plus `/metrics` and `/mcp`. `/health` stays available for the
healthcheck. Tenant routes `/api/v1/tenants/{tenant}/...` require a fresh
AuthFortress `ai.read`/`ai.configure` authorization.

`PLATFORM_READ_ENABLED` remains `false` in this increment, so dashboard AI jobs
and usage still return 404 until a separate reviewed change supplies
`WEBHOOK_AGENT_CONTEXT_KEY` and enables that mode. Knowledge Base uses the
tenant-scoped document route and is covered by this boundary.

`/openapi.json`, `/docs` and `/redoc` remain reachable in tenant mode. They
disclose the API schema but no tenant data; disabling them is part of the
separate production-hardening step and is not claimed here.

## Host overrides

The runbook's four local override files under `.venv/` are gitignored and are
not part of this commit. The last override, `root-local-hardening.compose.yml`,
must be kept consistent with this boundary:

- keep `agent_service.command` running `python /app/agent_platform_preflight.py`
  before `exec uvicorn app.main:app ...`;
- set `PLATFORM_TENANT_ENABLED: "true"` for `agent_service`;
- do not override the `agent_service` healthcheck with a `/health`-only probe;
- if the pinned image predates tenant support, rebuild or upgrade the AgentHub
  image from a tenant-aware revision and run the matching forward migration
  before restarting. Otherwise the preflight/healthcheck fail closed.

The README front-page status and the dated local-hardening receipt predate this
boundary; amend their status wording during the host rollout. The override file
itself is the applied configuration and must carry the preflight command.

The preflight and healthcheck scripts are mounted read-only from this reviewed
root tree; the image digest does not cover them. Keep them mode `0644` so UID
10001 can read them. A future packaging step can bake them into a root-built
wrapper image and pin its digest.

## Operational effects

- Prometheus scraping of AgentHub `/metrics` stops while tenant mode is active.
  Add an authenticated/internal metrics path separately; do not reopen `/metrics`.
- MCP clients must use an explicitly reviewed authenticated deployment instead
  of the integrated root.
- Existing NULL-tenant rows remain in place. No backfill or deletion is part of
  this change.

## Verification

`tests/test_verify_platform_agent_boundary.py` proves the preflight rejects a
missing/disabled `tenant_enabled`, accepts an enabled revision, exercises the
configuration-unavailable path, checks the healthcheck against a real local HTTP
server, and asserts the Compose healthcheck/mount/flag and the single
`.env.example` secure default. The AgentHub route matrix is covered by its own
platform tests; the local tenant-mode matrix was also checked with an in-process
TestClient against the build context.

## Rollback

Set `PLATFORM_TENANT_ENABLED=false`, restore the previous `agent_service.command`
and healthcheck, and remove the preflight/healthcheck bind mounts to restore the
legacy standalone API. No schema or data migration is involved; the rollback
reopens the previously documented local-only surface, so it must be paired with
network isolation and a reviewed exception.
