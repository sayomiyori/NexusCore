# Auth/session hardening (Stage B)

Cross-service contract for the AuthFortress changes in this increment.

Status of the current 2FA increment: verified in isolated local tests, no live
rollout. See "Two-factor state changes" and "Acceptance evidence" below; the
earlier Stage B material keeps its original scope.

## JWT secret

AuthFortress rejects the historical defaults, the root `.env.example`
placeholder, the standalone Compose default and the old README example, and
requires a secret with at least 32 bytes and at least eight distinct characters,
without leading/trailing whitespace. Root `.env.example` no longer supplies a
usable placeholder: Compose's required-variable check fails before startup until
an operator generates independent `AUTH_SECRET_KEY` and `WEBHOOK_SECRET_KEY`
values. AuthFortress's own Compose now requires `JWT_SECRET_KEY` instead of
defaulting to a public value.

## Access and refresh tokens

An access token is accepted only when:

- the signature, `type=access`, `exp` and `sid` are valid;
- a `UserSession` row with that `sid` exists, is not revoked and is not expired;
- `session.user_id` equals the token `sub`;
- the Redis `session:{sid}` key exists;
- the user is active.

Refresh rotation additionally requires the refresh token `sub` to equal
`session.user_id`. Logout and admin session revocation delete both the database
revocation marker and the Redis key; the database check closes the
Redis-restore/direct-DB-revocation gap.

## Credential changes and admin actions

- Changing a password or email revokes all of the target user's sessions; a
  self-service change keeps only the caller's current session. The credential
  change and the database revocations commit together, and login takes the same
  user-row lock so a concurrent old-password login cannot create a surviving
  session. Redis keys are deleted after the commit; the access-token database
  check still rejects a revoked row if a Redis delete fails.
- `PATCH /api/v1/users/{id}` and `PATCH /api/v1/admin/users/{id}/block` follow
  one rule: an admin may manage lower roles and themselves; only a superadmin
  may manage a peer admin or superadmin. Admin-to-admin password reset,
  blocking and session revocation are denied.
- New user CRUD audit rows record the target UUID, password/email/username/
  role/active change flags and the number of newly revoked sessions, but never
  passwords, tokens or email values. No-op updates do not write an audit row.
  Self-deletion writes a null actor to avoid a foreign-key failure after the
  irreversible delete. Pre-existing registration/login audit rows still contain
  the submitted email; that separate privacy change is not claimed here.

## OAuth linking

An OAuth callback never auto-links to an existing local account by email. A
matching email returns `409` until an explicit, authenticated linking flow is
implemented. Existing `(provider, provider_user_id)` links continue to log in.
This closes the pre-registered-email pre-hijack; email verification remains a
required follow-up for account-squatting and Yandex's unverified-email behavior.

## Two-factor state changes

Status: verified in isolated local tests in the AuthFortress worktree; no live
rollout and no deployment. The defect narrative and its evidence live in the
AuthFortress repository at `AuthFortress/docs/ERRORS.md`, entry `2026-11-01`,
with the implementation in `app/api/v1/auth.py`, `app/services/auth_service.py`
and `app/api/v1/oauth.py` and the regressions in
`tests/test_2fa_session_boundary.py`, `tests/test_oauth_issuance_boundary.py` and
`tests/test_twofa.py`.

- `POST /api/v1/auth/2fa/setup`, `/2fa/verify` and `/2fa/disable` lock the user
  row, then re-read the caller's own session under that lock: the database row
  must exist, be unrevoked and unexpired, and the Redis `session:{sid}` key must
  still be present. A caller whose session ended while it waited receives `401`
  instead of acting on the request-start snapshot.
- Enabling and disabling 2FA revoke every other session of that user and keep
  only the calling session; the audit row records the number of revoked sessions.
- `POST /api/v1/auth/login/2fa` holds the same user-row lock from backup-code
  consumption until the session is issued, so code consumption and issuance are
  serialized against a concurrent 2FA state change.
- The OAuth callback re-reads the user under the row lock before issuing tokens
  and writes its audit row after issuance, so the audit commit cannot release the
  lock while a session is being created.

### Step-up password for enrolment

Status: verified in isolated local tests; no live rollout.

- `POST /api/v1/auth/2fa/setup` and `POST /api/v1/auth/2fa/verify` both require a
  `current_password` field in the request body, checked with the existing bcrypt
  helper under the same user-row lock. A stolen access token alone cannot enrol
  or confirm an authenticator.
- Denial is generic. A missing, wrong, oversized or malformed-Unicode password,
  and an account with no local password, all produce the same `400`/`422`
  password error. There is no distinct "no local password" message and the
  submitted value is never echoed. A failed attempt revokes nothing.
- Step-up attempts are bounded at five per account per 60 seconds, shared by
  setup and verify, and evaluated before bcrypt and before the user-row lock. The
  budget is independent of the login and 2FA-disable limiters.
- Accounts whose `hashed_password` is `None` (OAuth-only users) therefore cannot
  enrol until a separate OAuth re-authentication flow exists. OAuth login itself
  is unchanged.
- The existing admin credential-reset endpoint stays admin-only: it is not an
  ordinary-user password setter and is not a bypass for the step-up requirement.
  No admin redesign is part of this increment.

## Acceptance evidence

Run in the AuthFortress worktree against an isolated PostgreSQL/Redis pair with
`DATABASE_URL == TEST_DATABASE_URL`: minimal pair 2 passed / audit 0, full suite
231 passed in 54.63 s / audit 0, audit repeat 1 passed / audit 0. Twenty-one
synthetic HTTP edge controls passed: old-hash password change, invalid input on
both 2FA routes, the shared account budget across sessions evaluated before the
lock and before bcrypt, OAuth-only login and denial, and the OAuth lock and
change paths. Ruff and Mypy are clean (39 files). A pristine `116ffdb` control
fails thirteen of these regressions, so the tests discriminate the old behaviour.
This is local acceptance only: no live rollout, no deployment and no production
data.

## Residuals

- No email verification or explicit OAuth linking flow yet.
- OAuth-only accounts cannot enrol 2FA until a separate OAuth re-authentication
  flow exists.
- Historical Stage B note: the integration tests of that stage required
  disposable PostgreSQL/Redis and were not part of the local unit pass at the
  time. The current isolated acceptance above ran against a real
  PostgreSQL/Redis pair.
