# Legacy WebHook auth hardening (Stage D2)

The root keeps `PLATFORM_BOTS_ENABLED=false` by default, so WebHook Manager's
legacy API remains reachable on its loopback port. This increment hardens that
surface without changing the platform-mode contract.

## Changes

- `RegisterRequest` normalizes/validates the email (trims whitespace, preserves
  case for legacy compatibility) and requires at least 6 characters and at most
  72 UTF-8 bytes (minimum by character count, maximum by encoded byte length).
  `LoginRequest` trims the identifier and caps the password at 72 UTF-8 bytes.
  Empty registration passwords are rejected.
- `POST /api/v1/auth/register` and `/login` share a per-source rate limiter
  (60 attempts/minute, DB-backed, `auth:<client-host>`). There is no Redis
  dependency for this legacy limiter. Denied attempts do not extend the window,
  but a source that continuously consumes its 60/min quota can still keep the
  shared bucket saturated; the real mitigation is per-client identity or not
  exposing the legacy port. A 60/min burst can block the loopback bucket for the
  remaining window.
- Root Compose sets WebHook `CORS_ORIGINS` to the dashboard origin and
  `TRUSTED_HOSTS` to loopback/localhost/`webhook_service`; the previous defaults
  were `*` / `*`. The webhook uvicorn command also pins `--no-proxy-headers` so
  the client-host limiter cannot be bypassed with `X-Forwarded-For`.

## Compatibility

The legacy login only returns `user_id`; it does not issue a session or API key.
A minimum of six characters preserves existing local clients/tests, including
the synthetic `"unused"` registration in the isolated delivery test. Login
rejects an empty password with 422 and caps it at 72 UTF-8 bytes. The stronger
policy remains AuthFortress (8+ bytes with complexity) for the integrated
platform identity path.

## Residuals

- Legacy passwords can still be weak (six characters) and login does not mint
  credentials; this is a legacy surface, not the platform identity path.
- The limiter is per source IP; all loopback clients share one bucket. It bounds
  abuse but is not per-account, and a 60/min burst can briefly block the shared
  bucket.
- Platform mode (`PLATFORM_BOTS_ENABLED=true`) remains the intended end state;
  this hardening only makes the legacy fallback safer.
- CORS restrictions do not affect the server-side dashboard BFF; they prevent
  arbitrary browser origins from using credential-bearing requests if cookie
  support is ever added.
- Email normalization preserves case (legacy exact-match lookup); mixed-case
  variants remain distinct accounts. A case-insensitive migration is separate.
- Login trims but does not format-validate the identifier, so legacy rows with
  `user@localhost`, a bare name, IDN or other non-conforming but
  untrimmed-equal values remain reachable. New registrations require the
  stricter ASCII dotted-domain pattern.
- Oversized/malformed validation errors may echo the submitted value unless the
  WebHook `main.py` sanitizer is included in the deployed revision; verify that
  before shipping. Standalone WebHook Compose files outside the root still use
  the `*` CORS/TrustedHost defaults.

## Verification

- `tests/unit/test_auth_schemas.py` covers email normalization, invalid emails,
  and password boundaries.
- `tests/unit/test_rate_limit_dependencies.py` covers the auth limiter key,
  429/allow paths and `count_denied=False` with a fake limiter.
- `tests/unit/test_auth_route_rate_limit.py` proves `/auth/login` and
  `/auth/register` return 429 through the ASGI app with `limit=60`, and that
  the limiter runs before body validation.
- `tests/test_verify_webhook_hardening.py` checks the Compose CORS/TrustedHost
  values and this spec.
- Full WebHook integration/e2e requires disposable PostgreSQL/Redis; it was not
  run in this increment because the Docker engine was unavailable.
