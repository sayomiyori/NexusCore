# Stage F runtime and response hardening — acceptance (2026-10-30)

Receipt for `specs/runtime-hardening.md`. Scope is NexusCore-owned files only:
the dashboard Next config and `docker-compose.yml`. No sibling service source
tree was modified, and the live `nexus_net` stack was not recreated.

## Dashboard headers

- `dashboard/next.config.ts` returns one `/(.*)` rule with CSP,
  `Cross-Origin-Opener-Policy`, `Permissions-Policy`, `Referrer-Policy`,
  `X-Content-Type-Options` and `X-Frame-Options`; `poweredByHeader` stays false.
- The CSP is built per call, so `script-src` carries `'unsafe-eval'` only when
  `NODE_ENV !== "production"`.
- `dashboard/tests/security-headers.test.ts` imports the real config and asserts
  every value, `frame-ancestors 'none'`, no `unsafe-eval` in production and its
  presence in development.
- Dashboard suite: **88 tests pass** (85 before this increment), lint and
  typecheck clean.

## Compose runtime defaults

- `x-default-logging` (`json-file`, `max-size: 10m`, `max-file: 3`) is applied to
  all 15 services; `x-api-hardening` (`read_only`, `cap_drop: ["ALL"]`,
  `tmpfs: ["/tmp"]`, `pids_limit: 256`) only to `auth_service`,
  `webhook_service` and `agent_service`.
- `tests/test_verify_runtime_hardening.py` parses the Compose file and asserts
  both blocks, that exactly the three API services carry the hardening, and that
  `no-new-privileges` is still present. Three tests pass.
- `docker compose config` resolves with a synthetic env file.

## Runtime proof for `read_only`

Each built API image was started **alongside** the live stack (same
`nexuscore_nexus_net` network, new container names) with
`--read-only --tmpfs /tmp --cap-drop ALL --pids-limit 256
--security-opt no-new-privileges:true`:

| Service | Result |
| --- | --- |
| `auth_service` | container running as uid 10001, `GET /health` → 200, root FS write rejected (`Read-only file system`), `/tmp` writable |
| `webhook_service` | container running as uid 10001, `GET /health/ready` → 200, same filesystem behavior |
| `agent_service` | preflight passed, `uvicorn` started, `agent_platform_healthcheck.py` exit 0 (health 200 and `/api/v1/documents`, `/metrics`, `/mcp/sse` closed), root FS read-only, `/tmp` writable |

`agent_service` used a disposable PostgreSQL with `init-scripts` plus
`redis:7-alpine` on the same network, because the running `nexus-agent-api`
container predates the current Compose environment and carries no
`AGENT_DB_PASSWORD`/`PLATFORM_TENANT_ENABLED`. The disposable containers and
their generated credentials were deleted afterwards.

This is also the first dynamic confirmation that the AgentHub preflight closes
the standalone `/api/v1/documents`, `/metrics` and `/mcp/sse` surface: without
the preflight the same healthcheck exits 2.

## Not covered

- Backend `/docs`, `/redoc`, `/openapi.json` and `/metrics` gating: blocked on
  the three sibling repositories settling their uncommitted work in the files
  that would change.
- No live-stack recreate, so the new Compose defaults are not yet active in the
  running demo containers.
- CSP nonces, HSTS, digest pinning and worker/datastore limits stay residuals.
