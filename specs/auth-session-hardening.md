# Auth/session hardening (Stage B)

Cross-service contract for the AuthFortress changes in this increment.

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

## Residuals

- No email verification or explicit OAuth linking flow yet.
- 2FA enable/disable does not revoke other sessions in this increment.
- Integration tests require disposable PostgreSQL/Redis and were not run in the
  local unit pass; the pure unit tests cover binding, revocation rows, RBAC and
  OAuth link decisions.
