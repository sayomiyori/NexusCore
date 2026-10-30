# Runtime and response hardening (Stage F)

This increment closes two gaps left by Stage E: the dashboard middleware did not
send the legacy framing header or cross-origin isolation, and the API containers
ran with writable root filesystems, full capability sets and unbounded container
logs. It touches only NexusCore-owned files. Backend `/docs`, `/openapi.json` and
`/metrics` gating stays a separate, explicitly blocked item (see Residuals).

## Dashboard response headers

`dashboard/proxy.ts` already sent a per-request nonce CSP (plus
`X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` and
`Cache-Control: private, no-store`) before this stage; `dashboard/next.config.ts`
only disabled `X-Powered-By`. That existing policy is the one that actually
ships, so it stays the single source of truth and the config object is left
alone.

This stage adds the two missing headers to the same middleware:

- `X-Frame-Options: DENY` for clients that ignore CSP `frame-ancestors`.
- `Cross-Origin-Opener-Policy: same-origin` so the dashboard is isolated from
  cross-origin window handles.

The production CSP remains strictly nonce-based with `'strict-dynamic'`,
`base-uri 'none'`, `object-src 'none'`, `form-action 'self'` and
`frame-ancestors 'none'`; `'unsafe-eval'` is still added only outside production
for hot reload.

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

- Dashboard `tests/security-headers.test.ts` calls the real `proxy()` function
  and asserts the emitted response headers: `nosniff`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`,
  `Cache-Control`, and the CSP shape (nonce, `'strict-dynamic'`,
  `frame-ancestors 'none'`, no `unsafe-` in production, `'unsafe-eval'` only in
  development). `tests/routes.test.ts` keeps its nonce-uniqueness and
  CSP-propagation assertions.
- `tests/test_verify_runtime_hardening.py` splits `docker-compose.yml` into
  service blocks and asserts the logging anchor on all 15 services, the exact
  content of both anchors, that `<<: *api_hardening` appears on exactly the three
  API services, and that they still carry `no-new-privileges`. It deliberately
  avoids a YAML dependency so the pinned CI check set is unchanged.
- `docker compose --profile "*" config` resolves with 15 services, exactly three
  `read_only` entries and the shared log options on all of them.

## Residuals

- Backend `/docs`, `/redoc`, `/openapi.json` and `/metrics` remain reachable on
  loopback-published ports. Disabling them belongs in each service's FastAPI
  constructor, and all three sibling repositories currently carry uncommitted
  work in the files that would change (`app/main.py`, `src/api/main.py`,
  `app/api/**`). That change must wait for those trees to settle; blocking it at
  a proxy would only cover the Telegram edge, not the loopback ports.
- HSTS is not set: the supported dashboard origin is plain-HTTP loopback and
  `__Host-` cookie names are still dormant until an HTTPS origin exists.
- Workers, PostgreSQL and Redis are not read-only and carry no PID/memory
  limits beyond the log rotation.
- Container images remain tag-pinned rather than digest-pinned.
- `AgentHub`'s Dockerfile does not set `PYTHONDONTWRITEBYTECODE=1`, so under
  `read_only` every import attempts a `.pyc` write that the interpreter ignores.
