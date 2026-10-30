# Security hardening acceptance — Stages A and B (2026-10-30)

This record covers the already-pushed AgentHub boundary and AuthFortress
identity hardening. It is an acceptance receipt, not a production-readiness
claim.

## Stage A — integrated AgentHub boundary

- Commit: `cd03391` (`fix(platform): fail closed on AgentHub legacy API`).
- `agent_service` runs `scripts/agent_platform_preflight.py` before uvicorn;
  `PLATFORM_TENANT_ENABLED` defaults to `true` in the integrated profile.
- The behavioural healthcheck `scripts/agent_platform_healthcheck.py` requires
  `/health` 200 and `/api/v1/documents`, `/metrics`, `/mcp/sse` 404.
- In-process TestClient against the build-context AgentHub with tenant mode:
  legacy documents/query/conversations/usage, `/metrics` and `/mcp` returned
  404; `/health` 200; tenant documents without a bearer returned 401.
- Preflight against the real AgentHub config: enabled -> 0, disabled -> 3,
  missing revision -> 2.
- Root suite at the time: 142 tests passed; reviewer approved after fixes.

## Stage B — JWT, sessions and OAuth

- AuthFortress commit: `4ee5b53`
  (`fix(auth): bind sessions and require explicit OAuth linking`).
- NexusCore commit: `f999fd9`
  (`fix(auth): remove usable signing-secret defaults`).
- Access tokens require an existing, non-revoked, non-expired `UserSession`
  whose `user_id` matches `sub`; refresh rotation also requires the subject to
  match. Logout/admin revocation clear the database marker and Redis key.
- Password/email changes revoke target sessions; self-change keeps the current
  session. User-row locking serializes login with credential changes.
- Admin user mutations are audited; peer-admin mutation/block/revocation is
  denied unless the actor is a superadmin.
- OAuth never auto-links an existing local account by email; it returns 409
  until an explicit linking flow exists.
- JWT secrets reject the historical placeholders, standalone Compose default,
  old README example, leading/trailing whitespace and low-entropy values.
- Full AuthFortress suite: **214 passed** against disposable PostgreSQL 16 and
  Redis 7; unit/config subset 26 passed; ruff, mypy and compileall clean.
- Residuals: no email verification or explicit OAuth linking flow; 2FA
  enable/disable does not revoke other sessions; OAuth callbacks do not take the
  user-row lock; legacy registration/login audit rows still contain email.

## Deployment note

The live stack was not restarted in either stage. The local hardening override
still pins pre-change image digests; the AuthFortress image must be rebuilt and
the override digest updated before the Stage B code is active. The AgentHub
override was updated locally to keep the preflight and tenant flag, but the
pinned image must be rebuilt if it predates tenant mode.
