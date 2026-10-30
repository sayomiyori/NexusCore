# Edge and runtime hardening (Stage E)

This increment covers the low-risk, code/config-only parts of Stage E. It does
not claim TLS, digest pinning, full read-only containers or backend security
headers; those remain deployment work.

## Telegram edge

`deploy/telegram-demo/default.conf.template` now keys connection limits by
`$telegram_client`: `CF-Connecting-IP` when Cloudflare provides it, otherwise
the peer address. The old `$server_name` key made every tunneled client share
one 16-connection bucket. This is per source address, not per Telegram user;
Telegram itself delivers from a small address set. A direct `nexus_net` caller
can spoof the header and create extra buckets, but such a caller can already
reach `webhook_service` directly. Nginx still caps the body, timeouts and
methods per request; the API remains responsible for webhook authentication.

## Dashboard cookies

On an HTTPS production dashboard origin the dashboard uses
`__Host-nexus_session` and `__Host-nexus_challenge` (Secure, no Domain,
Path=/). Production cookies remain `Secure` on HTTP loopback — the requirement
asserted in `tests/routes.test.ts` — but the legacy names are kept there because
`__Host-` requires HTTPS. The `__Host-` branch is currently **dormant** in the
supported topology: `privateOrigin` only accepts numeric loopback origins and
`next start` serves plain HTTP, so a TLS proxy/HTTPS-origin change is required
before it becomes active. `singleCookie` rejects duplicate cookie names before
the last-wins parser can select a shadowing value, including on DELETE, which
returns a bounded 400 and clears both cookie generations. This reduces cookie
tossing to a bounded failure rather than a session swap.

## Root required credentials and privileges

`.env.example` no longer supplies a usable PostgreSQL superuser password;
Compose requires `POSTGRES_USER`/`POSTGRES_PASSWORD` and fails before startup.
The AuthFortress, WebHook and AgentHub API services run with
`no-new-privileges:true`.

## Residuals

- Backend `/docs`, `/openapi.json` and `/metrics` remain reachable; a proxy or
  middleware change is separate.
- Images are still tag-pinned rather than digest-pinned; read-only filesystems,
  capability drops, memory/PID limits and log rotation are not included.
- TLS/mTLS between the dashboard BFF and services is not included. `Secure`
  remains on production loopback cookies; `__Host-` names require an HTTPS
  dashboard origin, which the current numeric-loopback validator and plain-HTTP
  `next start` cannot provide. The `__Host-` branch is prepared but dormant
  until a reviewed HTTPS-origin/TLS-proxy change.
- Registration/user enumeration and the remaining bot-token duplicate signal
  are not changed in this increment.
- The Telegram edge per-client key depends on the proxy forwarding a trustworthy
  client header; a direct `nexus_net` caller can spoof it. The same actor can
  also exhaust the 64k `limit_conn_zone` node table, after which new keys stop
  being throttled (and `error_log /dev/null` hides the warning) — an accepted
  risk for an already-trusted network position, not a Telegram-facing one.
- `no-new-privileges` is applied to the AuthFortress, WebHook and AgentHub API
  services; workers, PostgreSQL and Redis are not included.

## Verification

- `tests/test_verify_edge_hardening.py` checks the nginx client key and
  `tests/test_verify_runtime_hardening.py` checks the required PostgreSQL
  variables and API `no-new-privileges`.
- `nginx -t` against the rendered template in `nginx:1.30.5-alpine` passes;
  `nginx -T` keeps `map $http_cf_connecting_ip $telegram_client` and
  `limit_conn_zone $telegram_client` after `NGINX_ENVSUBST_FILTER` expansion.
  `docker compose config` resolves with three `no-new-privileges` entries, and
  `docker compose --env-file .env.example config` exits 1 until the required
  credentials (PostgreSQL superuser, service DB and Redis passwords, auth and
  webhook secret keys) are supplied (intended fail-closed behavior).
- Dashboard `tests/cookie-hardening.test.ts` checks `__Host-` names, duplicate
  rejection (dev and production DELETE), guard acceptance/rejection and the
  single-cookie path. `tests/routes.test.ts` pins both production paths: an
  HTTPS origin emits `__Host-nexus_session` (Secure/HttpOnly/SameSite=strict,
  Path=/, no Domain), and an HTTP loopback origin keeps `nexus_session` while
  still emitting `Secure`. That second assertion is what stops `Secure` from
  silently re-coupling to the HTTPS gate.
- Full stack/browser acceptance (live `nexus_net` edge, real client keys,
  browser login) was not run in this increment. The `__Host-` branch stays
  dormant until an HTTPS origin exists, so no browser flow exercises it.
