# Login rate limiting and proxy trust

This increment reduces the shared-dashboard lockout (NC-02) by making
per-account limiting primary; a 300/min shared-egress ceiling remains, so a
sustained burst can still deny login temporarily. It also closes the
`X-Forwarded-For` bypass (NC-16) on the supported Compose/README paths without
changing the login API.

## Issuer

AuthFortress limits password login by an HMAC-SHA256 of the normalized email,
keyed by the JWT secret (5 attempts per 60 seconds), and keeps a coarse
per-source ceiling of 300 attempts per minute. The account key is primary: the
root dashboard reaches the issuer through one shared egress address, so a low
per-IP limit would let one attacker lock out every account. The account key
never contains the email address and is not a plain unsalted digest.
Registration and 2FA retain their own IP/user limits.

A targeted account can still be locked for the window by repeated failures; a
sustained 300/min burst can also trip the coarse shared-egress ceiling. These
are accepted trade-offs until progressive delays or CAPTCHA are added. The
existing 2FA per-user limiter is unchanged.

## Dashboard BFF

`POST /api/session` applies a bounded in-memory per-account limiter
(5 attempts per 60 seconds, salted SHA-256 key) before calling the issuer. It
returns `429` without an upstream request. The limiter is per process; a
multi-instance deployment needs a shared Redis-backed limiter. The issuer's
per-account limit remains authoritative and durable.

## Proxy headers

The root Compose auth command and AuthFortress Compose use
`uvicorn --no-proxy-headers`. A direct loopback client cannot spoof
`X-Forwarded-For` to bypass limits or forge audit IPs.

If AuthFortress is placed behind a reverse proxy later:

- enable `--proxy-headers` and set `--forwarded-allow-ips` to the proxy CIDR;
- make the proxy overwrite, not append, the client-supplied
  `X-Forwarded-For`;
- keep the issuer port off public interfaces and re-run the account-isolation
  tests.

The standalone AuthFortress Dockerfile CMD and a directly launched `uvicorn`
without the flag still use uvicorn's default proxy-header trust from loopback.
The Compose and README paths covered here are the supported local paths; a
direct launch must add `--no-proxy-headers` for the same guarantee.

## Tests

- AuthFortress: per-account isolation (A locked, B still 401), HMAC-keyed Redis
  keys, casing-variant bucket reuse, and `_client_ip` ignoring X-Forwarded-For.
- Dashboard: pure clock-controlled limiter tests plus a BFF test proving five
  failures for account A return 429 while account B still reaches the issuer.
- NexusCore: Compose contains `--no-proxy-headers`; signing defaults remain
  empty and fail closed.

## Residuals

- Per-account lockout is possible for the 60-second window.
- A sustained 300/min burst can still trip the coarse shared-egress ceiling.
- BFF limiter is not shared across processes.
- Direct Dockerfile/direct-uvicorn launches without the flag retain uvicorn's
  loopback proxy-header trust; the supported Compose/README paths disable it.
- A future proxy deployment needs the explicit trusted-CIDR/overwrite review.
