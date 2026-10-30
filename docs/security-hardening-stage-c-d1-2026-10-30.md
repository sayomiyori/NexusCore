# Security hardening acceptance — Stages C and D1 (2026-10-30)

This record covers the already-pushed infrastructure authentication and login
rate-limit changes. It is an acceptance receipt, not a production-readiness
claim.

## Stage C — Redis AUTH and per-service PostgreSQL roles

- Commit: `fb1e077`
  (`feat(infra): authenticate Redis and scope service databases`).
- Redis requires `REDIS_PASSWORD`; every `REDIS_URL`/`CELERY_BROKER_URL`
  carries it, and the healthcheck authenticates via `REDISCLI_AUTH`.
- Runtime services use `auth_service`, `webhook_service` and `agent_service`
  roles instead of the PostgreSQL superuser.
- Fresh volumes use `init-scripts/02-create-service-roles.sh`; existing volumes
  use `scripts/provision-service-db-roles.sh` (manual, reviewed, with ownership
  reassignment for tables, sequences, enums, views, materialized views and
  functions, plus `vector`).
- Static verification: 148 root tests passed, both shell scripts pass `bash -n`,
  `docker-compose.yml` parses, a synthetic-compose `config --quiet` exits 0, and
  `.env.example` fails closed.
- Dynamic PostgreSQL/Redis acceptance is **closed**: see
  `docs/security-hardening-stage-c-dynamic-2026-10-30.md` for the disposable
  fresh-volume and existing-volume runs (role isolation, cross-database `CONNECT`
  denial, Alembic as each role, Redis `NOAUTH`/`PONG`).
- The live stack was not restarted. Existing `.env` lacks the three DB
  passwords, so compose commands fail closed until rollout step 1.

## Stage D1 — per-account login limits and proxy trust

- AuthFortress commit: `116ffdb` (`fix(auth): limit login per account`).
- NexusCore commit: `0d67534`
  (`fix(dashboard): limit login attempts per account`).
- Password login is limited per HMAC-keyed normalized email (5/min), with a
  coarse 300/min per-source ceiling. The account key uses `JWT_SECRET_KEY`, so
  Redis keys do not contain emails.
- The dashboard BFF applies a bounded in-memory 5/min per-account limiter before
  the issuer call; it returns 429 without an upstream request.
- Supported Compose/README paths pin `uvicorn --no-proxy-headers` so a loopback
  client cannot spoof `X-Forwarded-For`.
- Full AuthFortress suite: **216 passed** on disposable PostgreSQL 16 + Redis 7;
  dashboard **79 passed**, typecheck/lint clean; NexusCore **145 tests** passed.
- Residuals: a targeted account can be locked for the window; a sustained
  300/min burst can still block the shared egress; the BFF limiter is
  per-process; direct Dockerfile/uvicorn launches without the flag retain
  loopback proxy-header trust.

## Deployment note

Stage D1 code is not active in the live stack until the AuthFortress image is
rebuilt/pinned and the dashboard process is restarted. Stage C requires role
provisioning plus a Redis and application restart; see
`specs/infra-auth.md`.
