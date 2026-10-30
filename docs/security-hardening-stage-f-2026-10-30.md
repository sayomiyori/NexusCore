# Stage F runtime and response hardening — acceptance (2026-10-30)

Receipt for `specs/runtime-hardening.md`. Scope is NexusCore-owned files only:
`dashboard/proxy.ts` and `docker-compose.yml`. No sibling service source tree was
modified and the live `nexus_net` stack was not recreated.

## Dashboard headers — what actually changed

The dashboard already sent a per-request nonce CSP plus `nosniff`,
`Referrer-Policy`, `Permissions-Policy` and `Cache-Control: private, no-store`
from `dashboard/proxy.ts`, and `next.config.ts` already disabled `X-Powered-By`.
The real gaps were `X-Frame-Options` and `Cross-Origin-Opener-Policy`; both are
now set in the same middleware, so the nonce CSP stays the single source of
truth and no second policy is served.

- `dashboard/tests/security-headers.test.ts` calls the exported `proxy()`
  function and asserts the response headers it emits: `nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Permissions-Policy`, `Cross-Origin-Opener-Policy: same-origin`,
  `Cache-Control: no-store`, plus the CSP shape (nonce, `'strict-dynamic'`,
  `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'none'`,
  `form-action 'self'`, no `unsafe-` token in production, `'unsafe-eval'` only
  in development) and a fresh nonce per response.
- Dashboard suite: **88 tests pass**, lint and typecheck clean. `next build`
  succeeds and the route table shows the middleware active.

An earlier draft of this commit added a second CSP to `next.config.ts`; that was
wrong — the config rule never reaches page or API responses because the
middleware overrides it, and it described a weaker policy than the one that
ships. It was removed before this receipt was written.

## Compose runtime defaults

- `x-default-logging` (`json-file`, `max-size: 10m`, `max-file: 3`) is applied to
  all 15 services; `x-api-hardening` (`read_only`, `cap_drop: ["ALL"]`,
  `tmpfs: ["/tmp"]`, `pids_limit: 256`) only to `auth_service`,
  `webhook_service` and `agent_service`.
- `tests/test_verify_runtime_hardening.py` splits the compose file into service
  blocks without a YAML dependency and asserts: the logging anchor on every one
  of the 15 services, both anchor contents, `<<: *api_hardening` on exactly the
  three API services, `no-new-privileges` still present there, and no
  `read_only`/`cap_drop` leaking into the others. Four tests pass.
- `docker compose --profile "*" config` resolves with 15 services, exactly three
  `read_only` entries and the shared log options on all of them.

## Runtime proof for `read_only`

Each built API image was started **alongside** the live stack (same
`nexuscore_nexus_net` network, new container names) with
`--read-only --tmpfs /tmp --cap-drop ALL --pids-limit 256
--security-opt no-new-privileges:true`:

| Service | Result |
| --- | --- |
| `auth_service` | running as uid 10001, `GET /health` → 200, root FS write rejected (`Read-only file system`), `/tmp` writable |
| `webhook_service` | running as uid 10001, `GET /health/ready` → 200, same filesystem behavior |
| `agent_service` | preflight passed, `uvicorn` started, `agent_platform_healthcheck.py` exit 0, root FS read-only, `/tmp` writable |

For `agent_service` a disposable PostgreSQL with `init-scripts` and
`redis:7-alpine` were used on the same network, because the running
`nexus-agent-api` container predates the current Compose environment and carries
no `AGENT_DB_PASSWORD`/`PLATFORM_TENANT_ENABLED`. All disposable containers and
their generated credentials were deleted afterwards.

The AgentHub healthcheck requires `PLATFORM_TENANT_ENABLED=true` (the preflight
gate) and then probes `/health`, `/api/v1/documents`, `/metrics` and `/mcp/sse`;
the unscoped routes are closed by AgentHub's own `close_unscoped_resources`
middleware, not by the preflight script. Running the same image without the
preflight made the healthcheck exit 2, which is the evidence that the gate
matters.

## Not covered

- Backend `/docs`, `/redoc`, `/openapi.json` and `/metrics` gating in AuthFortress
  and WebHook Manager: blocked on those repositories settling their uncommitted
  work in the files that would change.
- No live-stack recreate, so the new Compose defaults are not yet active in the
  running demo containers.
- HSTS, digest pinning and worker/datastore limits stay residuals.
