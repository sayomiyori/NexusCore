# Runtime and response hardening (Stage F)

This increment covers two NexusCore-owned gaps left by Stage E: the dashboard
sent no security response headers, and the API containers ran with writable root
filesystems, full capability sets and unbounded container logs. It does not
change any sibling service source tree, so backend `/docs`, `/openapi.json` and
`/metrics` gating stays a separate, explicitly blocked item (see Residuals).

## Dashboard response headers

`dashboard/next.config.ts` sends a fixed header set on `/(.*)`:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` denying camera, microphone, geolocation and interest
  cohorts
- `Cross-Origin-Opener-Policy: same-origin`
- `Content-Security-Policy` with `default-src 'self'`, `frame-ancestors 'none'`,
  `base-uri 'self'`, `form-action 'self'`, `img-src 'self' data:`,
  `style-src 'self' 'unsafe-inline'`, `script-src 'self' 'unsafe-inline'` and
  `connect-src 'self'`

`poweredByHeader` stays off, so `X-Powered-By` is still absent.

The CSP keeps `'unsafe-inline'` for scripts and styles because Next.js injects
inline bootstrap/hydration code and there is no nonce plumbing yet. That is
recorded as a residual rather than hidden. Development adds `'unsafe-eval'` so
the dev server keeps working; production builds do not.

## Container runtime defaults

`docker-compose.yml` gains two reusable blocks:

- `x-default-logging`: `json-file` driver with `max-size: 10m` and
  `max-file: 3`, applied to every service so container logs cannot fill the
  host disk.
- `x-api-hardening`: `read_only: true`, `cap_drop: ["ALL"]`,
  `tmpfs: ["/tmp"]` and `pids_limit: 256`, applied to `auth_service`,
  `webhook_service` and `agent_service`.

The three API containers keep `security_opt: ["no-new-privileges:true"]` from
Stage E. `agent_service` keeps its writable uploads volume, which `read_only`
does not affect.

Workers, PostgreSQL and Redis are deliberately unchanged: they need writable
data directories and Celery spools, and their limits are a separate decision.
They still get the log rotation from the shared logging block.

## Verification

- Dashboard `tests/security-headers.test.ts` imports the real config and asserts
  every header value, `frame-ancestors 'none'`, absence of `unsafe-eval` in
  production, and its presence in development.
- `tests/test_verify_runtime_hardening.py` asserts the resolved Compose
  structure: the logging block on every service, `read_only`/`cap_drop`/
  `tmpfs`/`pids_limit` on exactly the three API services, and
  `no-new-privileges` still present.
- `docker compose config` must resolve; the three built API images were started
  with `--read-only --tmpfs /tmp --cap-drop ALL` alongside the live stack and
  answered their health endpoints, which is the runtime proof behind
  `read_only`. Details and the disposable PostgreSQL/Redis used for
  `agent_service` are in
  `docs/security-hardening-stage-f-2026-10-30.md`.

## Residuals

- Backend `/docs`, `/redoc`, `/openapi.json` and `/metrics` remain reachable on
  loopback-published ports. Disabling them belongs in each service's FastAPI
  constructor, and all three sibling repositories currently carry uncommitted
  work in the files that would change (`app/main.py`, `src/api/main.py`,
  `app/api/**`). That change must wait for those trees to settle; blocking it at
  a proxy would only cover the Telegram edge, not the loopback ports.
- CSP still allows inline scripts/styles; a nonce-based policy needs per-request
  middleware.
- HSTS is not set: the supported dashboard origin is plain-HTTP loopback and
  `__Host-` cookie names are still dormant until an HTTPS origin exists.
- Workers, PostgreSQL and Redis are not read-only and carry no PID/memory
  limits beyond the log rotation.
- Container images remain tag-pinned rather than digest-pinned.
