# Stage E acceptance — edge and runtime hardening (2026-10-30)

This receipt closes the pending container/browser acceptance for the Stage E
commits `7501fc0`, `1da79f7`, `7da560d` and `31aa754` (contained in `main`
`3b1927d`). No product code, configuration or test was changed for this pass.
The live `nexus_net` stack was not restarted and no existing volume, database
or sibling repository was touched.

Later commits on `main` (Stages F and G: logging, read-only containers,
capability drops, security headers, digest pins) are outside this receipt.

## Scope of Stage E

| Commit | Files |
| --- | --- |
| `7501fc0` | `dashboard/app/api/session/route.ts`, `dashboard/lib/server.ts`, `dashboard/package.json`, `dashboard/tests/cookie-hardening.test.ts`, `dashboard/tests/routes.test.ts` |
| `1da79f7` | `deploy/telegram-demo/default.conf.template`, `docs/telegram-demo.md`, `tests/test_verify_edge_hardening.py` |
| `7da560d` | `.env.example`, `docker-compose.yml`, `tests/test_verify_runtime_hardening.py` |
| `31aa754` | `specs/edge-hardening.md` |

Behaviour under test: per-client nginx connection keys, required PostgreSQL
superuser credentials, `no-new-privileges` on the three API services, duplicate
session-cookie rejection and the prepared `__Host-` cookie names.

## Environment

- Windows host, Docker engine `29.8.2`, Node `24.11.0`, Python `3.12`.
- Because `main` received concurrent Stages F/G work while this pass ran, all
  repository checks were executed in a separate worktree at `3b1927d`
  (`D:/Programming/NexusCore-stage-e-acceptance`, detached, clean) with the
  existing `dashboard/node_modules` junctioned read-through for the duration of
  the run. The main working tree was not modified by the checks; only this
  receipt is added to it.
- Service images are the pinned fixture images already used by the project:
  AuthFortress `sha256:65256ce…`, WebHook `sha256:7cae102…`, AgentHub
  `sha256:2daa64d…`/`sha256:e877ed3…`, `pgvector/pgvector:pg16`,
  `redis:7-alpine`, `nginx:1.30.5-alpine`.

## Repository checks

| Check | Command | Result |
| --- | --- | --- |
| Python dependencies | `python -m pip check` | no broken requirements |
| Ruff | `python -m ruff check scripts tests` | all checks passed |
| Compile | `python -m compileall -q scripts tests` | clean |
| Root suite | `python -m unittest discover -s tests -p 'test_verify*.py'` | **152 passed OK** |
| Dashboard suite | `npm test` | **85 passed / 0 failed** |
| Dashboard lint | `npm run lint` | 57 files, no fixes |
| Dashboard types | `npm run typecheck` | clean |
| Dashboard build | `next build --webpack` | success, 12 routes |

`next build` was run with `--webpack` only in the isolated worktree: Turbopack
refuses the junctioned `node_modules` outside the workspace root. The committed
CI path uses the normal build and is green for `7501fc0`
(Dashboard checks run 2026-10-30T19:10:39Z); `1da79f7`, `7da560d` and
`3b1927d` passed Local verification checks the same day.

## Compose and nginx

| Check | Result |
| --- | --- |
| `docker compose --env-file .env.example config --quiet` | exit 1 — fails closed until credentials are supplied |
| `docker compose config --quiet` without new credentials | exit 1 |
| `docker compose config` with synthetic `POSTGRES_*`, `*_DB_PASSWORD`, `REDIS_PASSWORD`, `*_SECRET_KEY` | exit 0 |
| `security_opt: ["no-new-privileges:true"]` present exactly on | `auth_service`, `webhook_service`, `agent_service` |
| `nginx -t` on the rendered template (`NGINX_ENVSUBST_FILTER=^TELEGRAM_DEMO_BOT_ID$`) | syntax ok, test successful |
| `nginx -T` after envsubst | keeps `map $http_cf_connecting_ip $telegram_client` (line 145) and `limit_conn_zone $telegram_client zone=telegram_demo:64k` (line 150) |

## Telegram edge acceptance

The tracked driver was re-run first:

```powershell
python scripts/verify_telegram_edge.py --python-image sha256:2daa64d…
```

It failed **before any assertion** while creating the fixture networks:
`all predefined address pools have been fully subnetted`. The host's Docker
default address pool is exhausted by retained historical fixture networks. This
is an environment/test-tooling condition, not a configuration defect: the
committed template renders and passes `nginx -t`.

Because that driver also cannot distinguish the Stage E change (its 16-slot
concurrency block uses one client key), an equivalent private probe was run
with the same overlay, the same receiver image and pinned fixture subnets. It
repeats every tracked assertion and adds the per-client checks:

| Check | Result |
| --- | --- |
| Exact route 202, forwarded body/encoding, no Authorization or Cookie forwarding | pass |
| `/`, `/docs`, `/openapi.json`, `/api/v1/tenants`, `/internal/v1/bots`, trailing slash, query, encoded alias, double slash, wrong suffix → 404 | pass |
| GET/HEAD/PUT/DELETE/OPTIONS → 405 | pass |
| 1 MiB body limit → 413 | pass |
| Missing/wrong/duplicated secret header → 401 | pass |
| 16 held connections on key `203.0.113.10` → next request on that key 503 | pass |
| Next request on key `203.0.113.11` → **202** (per-client bucket, the Stage E behaviour) | pass |
| Next request without the header (peer address bucket) → 202 | pass |
| Incomplete body is closed as idle timeout (408/close) within 4–10 s | pass |
| 16 distinct spoofed `CF-Connecting-IP` keys do not exhaust a 17th key | pass (documented residual) |
| Secret header never appears in edge logs | pass |
| Upstream stopped → 502/504, never a false receipt | pass |
| Receiver observed 7 admitted requests; fixture project removed | pass |

Before this change, the same 503 also applied to `203.0.113.11`, because the
zone was keyed by `$server_name`. The private probe is a receipt, not a shipped
test; see "Proposed tests" below.

## Browser acceptance

Fixture: existing ignored driver `.venv/verify_organizations_20261028.py`,
launched from the acceptance worktree. Six isolated synthetic containers
(PostgreSQL, Redis, callback receiver, AuthFortress, WebHook, AgentHub), pinned
subnet, loopback-only bridges, no external provider or Telegram traffic.

- Project `nexus-organizations-1cb6550526574f778025c7884bc862b8`.
- Driver receipt: `passed=true`, all six containers stopped with exit `0`,
  `external_calls_enabled=false`, `last_phase=production_http`.
- The driver itself asserted: owner/member document reads 50+2, empty and
  foreign tenant denial, logout, safe projection, unchanged provider counters,
  and – relevant here – that production HTTP still issues `nexus_session` with
  `HttpOnly`, `Secure` and `SameSite=strict`.

Real Chromium (`chromium-1228`, headless, driven over CDP without installing
packages) then exercised the production dashboard at that origin:

| Check | Result |
| --- | --- |
| Anonymous visit renders the sign-in form on `http://127.0.0.1:50228` | pass |
| Desktop 1280×800: `scrollWidth 1280`, body `1280`, no horizontal overflow | pass |
| Real form login reaches the signed-in workspace ("Sign out" visible) | pass |
| Exactly one `nexus_session` cookie after login | pass |
| Cookie flags: `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`, host-only | pass |
| No `__Host-` cookie on the HTTP loopback origin (legacy names preserved) | pass |
| `fetch('/api/tenants')` with the browser session → 200 | pass |
| Mobile 360×800 signed-in layout: `scrollWidth 360`, body `360`, no overflow | pass |
| Duplicate `nexus_session` on paths `/` and `/api` → protected read 400 | pass |
| `DELETE /api/session` with duplicates → 400, `path=/` generation cleared | pass |
| Fresh login, `DELETE /api/session` → 200 `{signedOut:true}` | pass |
| Session unusable afterwards (`/api/tenants` → 401) | pass |
| No `nexus_session` cookie remains after logout | pass |

15/15 browser checks passed. No production data, real Telegram or LLM call was
involved.

## Dormant HTTPS-origin branch

`__Host-` names activate only for `NODE_ENV=production` with an `https://`
`DASHBOARD_ORIGIN`, which the supported plain-HTTP loopback topology cannot
provide. To close the "2FA challenge under `__Host-`" and "existing session
invalidation" gaps without inventing a TLS deployment, the committed production
build was started with `DASHBOARD_ORIGIN=https://127.0.0.1:<port>` against a
loopback synthetic issuer, and driven at HTTP level with the matching `Host`
and `Origin` headers. The server-side policy is identical to a TLS deployment;
only transport encryption is absent.

| Check | Result |
| --- | --- |
| Password login 200 `{requires2fa:false}` | pass |
| Session cookie name `__Host-nexus_session`, `Secure`, `HttpOnly`, `SameSite=strict`, `Path=/`, `Max-Age=900`, no `Domain` | pass |
| Legacy `nexus_session` cookie → `/api/tenants` 401 (previous HTTPS session invalidated, by design) | pass |
| `__Host-nexus_session` → `/api/tenants` 200 with the projected tenant | pass |
| 2FA login 200 `{requires2fa:true}` and `__Host-nexus_session` cleared with `Max-Age=0` | pass |
| Challenge cookie `__Host-nexus_challenge`, `Max-Age=300`, `Secure`, `HttpOnly` | pass |
| Code exchange forwards the challenge value as `temp_token` to the issuer | pass |
| Successful 2FA sets `__Host-nexus_session` `Max-Age=900` and clears the challenge | pass |
| Duplicate `__Host-nexus_session` → DELETE 400 and name cleared | pass |
| Logout 200 reaches the issuer and clears both cookie generations (4 `Set-Cookie`) | pass |

15/15 checks passed.

## Findings and residuals

1. **P2 — the tracked edge driver does not regress the Stage E behaviour.**
   `scripts/verify_telegram_edge.py` holds all 16 connections from one client,
   so it passes identically with `$server_name` and `$telegram_client`. On this
   host it additionally cannot create networks until the default address pool
   is pinned. The shipped regression therefore covers rendering, not per-client
   throttling.
2. **P3 — a non-root-path duplicate survives logout.** In the browser run a
   `nexus_session` cookie on `/api` remained after the bounded 400 and would
   keep every dashboard request at 400 until the user clears cookies manually.
   This needs an actor able to set cookies for the same host (cookies ignore
   ports, so any other application on `127.0.0.1` qualifies). `__Host-` removes
   the domain-scoped variant on HTTPS but not host-only duplicates. Fail-closed
   behaviour is correct; recovery is not automatic.
3. **P3 — `__Host-` rollout invalidates existing sessions.** Expected and
   confirmed; it must be announced in the HTTPS-origin rollout, not treated as
   a regression.
4. **P3 — the `__Host-` branch has no committed end-to-end test.** Route tests
   pin both production paths and the helper names, and this receipt exercises
   the branch at runtime, but no shipped test asserts that the 2FA response
   emits `__Host-nexus_challenge` when the origin is HTTPS.
5. **P3 — the branch remains dormant** until a reviewed TLS proxy / HTTPS
   origin exists; no browser TLS check is possible without that deployment.

## Proposed tests (not implemented, awaiting approval)

1. `scripts/verify_telegram_edge.py`: pin fixture subnets (as the other
   drivers already do) and add `CF-Connecting-IP` headers to the concurrency
   block – 16 holds on key A, assert 503 on A, 202 on key B and 202 without the
   header. This makes the Stage E change a shipped regression instead of a
   private receipt, and lets the driver run on a host with an exhausted default
   pool.
2. `dashboard/tests/routes.test.ts`: repeat the existing 2FA test with
   `NODE_ENV=production` and an `https://` `DASHBOARD_ORIGIN`, asserting
   `__Host-nexus_challenge` and the `__Host-nexus_session` clearing header.
   The mock issuer already exists in that file, so the change is small and
   covers the one path only the runtime probe validates today.
3. Optional: on duplicate-cookie DELETE, also clear `path=/api` so a browser
   poisoned on the BFF prefix recovers without manual intervention.

## Not covered

- The live `nexus_net` edge, the real Cloudflare tunnel and real Telegram
  delivery; only an isolated overlay with the pinned nginx image was used.
- A TLS-terminating proxy and a browser over HTTPS; the `__Host-` policy was
  proven against a real production server, not through TLS transport.
- Stages F and G (logging, read-only containers, capability drops, headers,
  digest pins) and any rollout of Stages A–E to the running stack.
- Production data, existing volumes and database migrations.

## Status

**Stage E is accepted for the committed scope** (`7501fc0`, `1da79f7`,
`7da560d`, `31aa754`) with two explicit limits: the shipped edge driver does not
yet regress per-client throttling on this host, and the `__Host-` branch was
verified at server level rather than through a TLS browser. Neither limit
weakens the implemented behaviour; both are covered by the proposed tests.
