# Public dashboard onboarding flow

Let a client complete the whole product entry path in the browser with no
manual scripts and no repository-layer provisioning: create an account, create
an organization, register a bot (Telegram getMe verification), prepare and
configure its webhook, and reach first-reply readiness. Today the chain stops
halfway: the dashboard has sign-in and owner bot registration, but accounts and
tenants exist only through fixture scripts, and webhook apply is reachable only
through the backend API.

Status: specification only, Planned. Nothing in this document is implemented or
verified yet. Parent contracts: [dashboard-overview.md](dashboard-overview.md),
[dashboard-bots.md](dashboard-bots.md),
[dashboard-bot-registration.md](dashboard-bot-registration.md),
[dashboard-webhook-preview.md](dashboard-webhook-preview.md),
[bot-registration.md](bot-registration.md),
[telegram-ingress.md](telegram-ingress.md),
[telegram-ai-reply.md](telegram-ai-reply.md),
[integration-contracts.md](integration-contracts.md).

## Boundary

This is a dashboard-only increment. Every upstream endpoint already exists and
stays authoritative; the increment adds BFF routes and UI over them:

- AuthFortress `POST /api/v1/auth/register`, `POST /api/v1/auth/login`,
  `POST /api/v1/tenants` (creator becomes owner) — unchanged.
- WebHook Manager `POST /api/v1/tenants/{tenant}/bots` (getMe verification,
  encrypted credential storage) and
  `POST /api/v1/tenants/{tenant}/bots/{bot}/webhook` with
  `{"dry_run": true|false}` — unchanged.
- Existing dashboard routes `POST /api/session`, `GET /api/tenants`,
  `GET /api/bots`, `POST /api/bot-registration`,
  `POST /api/bot-webhook-preview` — unchanged.

No sibling repository, schema, migration, dependency, root Compose or
environment change. No public deployment, no live Telegram/LLM activation, no
capacity work (see Out of scope).

## Onboarding steps

| # | Step | Performed by | Confirmed by | Visible where |
|---|---|---|---|---|
| 1 | Create account | New BFF `POST /api/account-registration` → issuer register | Exact issuer success status; no auto sign-in | Sign-in screen |
| 2 | Sign in | Existing `POST /api/session` (login, optional 2FA) | Existing session contract | Workspace |
| 3 | Create organization | New BFF `POST /api/tenant-creation` → issuer create tenant | Exact 201, owner role, name echo | Organizations |
| 4 | Register bot | Existing `POST /api/bot-registration` → WebHook register | Existing 201 `BotView` contract | Bots |
| 5 | Verify token (getMe) | WebHook Manager inside registration; no separate control | getMe result decides the 201/400/409/429/503 above | Bots states |
| 6 | Prepare webhook | Existing `POST /api/bot-webhook-preview` (dry run) | Existing preview contract | Bots (owner) |
| 7 | Configure webhook | New BFF `POST /api/bot-webhook-setup` → backend apply | Exact 200 with `webhook_status: configured` | Bots stored status |
| 8 | First reply | Operator-authorized platform flags; outside this increment | First job/usage/event through existing reads | AI jobs, Events, Usage |

Step 5 is deliberately not a separate API: registration already verifies the
token with `GET /bot<token>/getMe` server-side, and a second endpoint would
duplicate that boundary. The UX section defines what each getMe outcome shows.

Step 8 is a readiness boundary, not an activation. Intake, admission, AI
processing and Telegram sending run only under the operator's separately
authorized flags (`PLATFORM_TELEGRAM_ENABLED`, `TELEGRAM_AI_ENABLED`,
`TELEGRAM_REPLIES_ENABLED` plus provider credentials). This spec never enables
them; it points the user at the existing AI jobs, Events and Usage sections
where the first reply appears as safe metadata once processing is activated.
Those read sections keep their own existing opt-in service flags (for example
`PLATFORM_READ_ENABLED` for AgentHub reads); fixture acceptance enables them
only inside the fixture and never on an existing stand.

## Roles

- Signed-in user with no organizations: may create an organization. The
  issuer's contract makes any active authenticated user the owner of a tenant
  they create; this is not a role escalation of an existing tenant.
- Owner of the selected tenant: all onboarding write controls — register bot,
  webhook preparation check, webhook setup — plus every member read.
- Member of the selected tenant: read-only exactly as today. No bot form, no
  preview, no setup control; members still may create their own new
  organization, where they become its owner.
- Revoked membership or changed role: existing denial behavior. Scoped reads
  fail authorization, Refresh returns the possibly empty directory, and
  owner-only controls disappear once the changed role is reflected. Global
  admin roles grant no membership bypass.
- Tenant selection from the browser is a selector, never authorization. Every
  BFF write repeats fresh issuer authorization before any upstream call, and
  the backend re-checks after that (existing invariant).

## New BFF contracts

All three routes are same-origin POSTs under the existing Host/Origin guards,
nonce CSP, private no-store responses, bounded JSON parser and fixed English
copy. None of them ever echoes or logs the password, email, token, webhook URL,
secret or ciphertext, and none sets cookies except through existing session
routes.

### POST /api/account-registration (no session)

- Accept exactly `{"email", "username", "password"}`; reject unknown, extra or
  duplicate fields. Local pre-bounds: each field a nonempty string of at most
  128 characters; the issuer's own validation remains authoritative and its
  422 maps to a generic local 422 without echoing input.
- Apply the existing login-style limiter first: 5 attempts per 60 seconds keyed
  by salted SHA-256 of the trimmed, lowercased email, plus a coarse per-process
  ceiling of 20 registrations per 60 seconds. Both return 429 without an
  upstream call.
- Make exactly one upstream `POST` to the issuer register route with only those
  three fields. Confirmed only on the issuer's documented success status (HTTP
  200 in both root smoke drivers; confirm the exact status and field bounds
  against the AuthFortress OpenAPI before merge). Do not trust or project the
  response body. Respond `201 {"created": true}`.
- Mapping: issuer duplicate email 409 → generic 409 copy that does not name the
  colliding field; 422 → generic 422; 429 → 429; any other status, transport
  failure or malformed reply → unconfirmed 502 fixed copy, no retry.
- No automatic sign-in: registration never returns or sets tokens. On success
  the UI routes to the existing sign-in form; the existing login rate limits,
  2FA and backup-code flow stay authoritative.
- UI: the sign-in screen gains a "Create account" toggle to a bounded form with
  email, username, password and a repeat-password field that never leaves the
  browser. There is no email verification or password reset in the platform,
  so the repeat field is the only typo guard. Submission locks navigation and
  clears both password fields before awaiting the server, mirroring the token
  cleanup rule.

### POST /api/tenant-creation (session required)

- Accept exactly `{"name"}`; name is trimmed to 1..128 Unicode code points,
  matching the issuer's `Tenant.name` grammar. Reject unknown, extra or
  duplicate fields.
- Limiter: 5 per 60 seconds keyed by salted SHA-256 of the presented access
  credential; 429 without an upstream call.
- Make exactly one upstream `POST /api/v1/tenants` with `{"name": ...}` and the
  caller's bearer under the existing bounded private transport. Confirmed only
  on exact 201 with canonical UUID `id`, `role` exactly `owner`, a name equal to
  the normalized submitted name and a valid UTC RFC3339 `created_at`. Respond
  `201 {"id", "name", "role": "owner", "createdAt"}` — a safe `TenantView`
  projection with no member list.
- Mapping: issuer 401 → 401 session expiry; 422 → generic 422; 429 → 429; any
  other status, transport failure or malformed body → unconfirmed 502 fixed
  copy, no retry.
- Idempotency residual: the issuer v1 has no idempotency key for tenant
  creation, and names are non-unique display labels. After an unconfirmed
  outcome an explicit user retry can create a second organization with the
  same name. Recovery is the documented path: refresh Organizations, keep the
  intended one. The BFF never retries and never invents a client-generated
  idempotency token the issuer does not understand.
- UI: the Organizations empty state (successful empty list, distinct from
  pending and failed) gains a "Create organization" control for any signed-in
  user. On confirmed success the client performs the existing first-page
  membership refresh and selects the returned organization when it appears; a
  created organization that does not appear after refresh stays an unconfirmed
  outcome, never a silent success.

### POST /api/bot-webhook-setup?tenant=UUID&bot=UUID (session, owner)

- Accept an exact empty JSON object and canonical UUID query parameters only,
  mirroring the preview route's query rules. Guard Host/Origin, session,
  canonical scope, then fresh issuer membership and owner role before any
  WebHook call. Members and foreign tenants are denied before upstream access.
- Limiter: 5 per 60 seconds keyed by salted SHA-256 of the credential plus the
  canonical bot UUID; 429 without an upstream call.
- Make exactly one upstream POST to the existing scoped backend webhook route
  with exactly `{"dry_run": false}`. Never send `replace_url`, any URL, secret
  or token from the browser; the operator-configured origin and the stored
  target remain backend-owned. The backend rechecks owner permission, bot
  membership and activity and serializes concurrent setups with its per-bot
  database claim.
- Confirmed only on exact upstream 200 whose body matches the canonical
  tenant/bot, carries a syntactically valid HTTPS webhook URL (validated,
  never returned) and `webhook_status` exactly `configured`. Respond
  `200 {"webhookStatus": "configured"}`.
- Mapping, all without provider messages: 400 invalid token → bounded 400;
  403 inactive bot/tenant or member → 403; 404 → 404; 409 live claim → bounded
  409 copy advising an inventory refresh; 502 permanent rejection → bounded
  copy stating the stored status is `failed`; 503 ambiguous or interrupted
  claim → unconfirmed copy stating the stored status may be `unknown`; any
  malformed or mismatched acknowledgement or unexpected status fails closed as
  an unconfirmed 502 without retry.
- UI: the Bots section gains an owner-only Setup control for active bots with
  explicit confirmation copy that this configures the Telegram webhook. The
  onboarding guide recommends passing the preparation check first; the backend
  does not require it and the control does not depend on UI-only preview
  state. On confirmed success the client refreshes the bot inventory so the
  stored webhook status is displayed. The control is never auto-invoked.
- On stands with the Telegram platform mode disabled, preview and setup fail
  closed with the existing bounded unavailable copy. Enabling platform modes
  on an existing stand is separate operator work, unchanged by this spec.

## Reused contracts and unchanged guarantees

- Bot registration, including backend token grammar, Unicode name limit, 4 KiB
  request cap, one-upstream-POST rule, status preservation
  (400/401/403/404/409/429) and the unconfirmed-outcome lock, stays exactly as
  specified in [dashboard-bot-registration.md](dashboard-bot-registration.md).
- Webhook preparation stays exactly as specified in
  [dashboard-webhook-preview.md](dashboard-webhook-preview.md); the BFF must
  never send `dry_run: false` through that route.
- Bot token encryption is backend-owned and unchanged: Fernet under
  `BOT_CREDENTIALS_KEY`, payload bound to bot and tenant IDs, webhook secret
  stored with its SHA-256 digest. The BFF never receives, stores, forwards or
  returns a token, ciphertext, webhook URL or secret; the registration form
  clears the token before awaiting the server (existing rule). The setup
  response carries only the safe status string.
- Sessions and cookies stay as hardened in
  [auth-session-hardening.md](auth-session-hardening.md) and
  [dashboard-overview.md](dashboard-overview.md): HttpOnly SameSite=Strict
  cookies, 15-minute access expiry, no automatic refresh, durable sign-out
  through the retained refresh credential. Dashboard cookie-path PR #19 was
  still open for independent review when this spec was written; it narrows
  legacy-path cookie clearing only and does not alter these contracts. Slice
  branches rebase on main after it merges and rerun the session suites.

## Idempotency and uncertain outcomes

- Every BFF write performs exactly one upstream POST per user action and
  never retries automatically. This extends the existing registration
  invariant to all three new routes.
- Backend identity guarantees remain authoritative: same-email registration
  resolves as a conflict; bot registration deduplicates by Telegram identity,
  so a retry after a lost 201 returns 409 with the same row; webhook apply is
  serialized by the per-bot claim, a configured identical target is a no-op,
  and an explicit repeated apply reuses exactly the same URL and secret.
- Tenant creation has no server-side idempotency key; the documented residual
  above is the honest limit. Uncertain outcomes everywhere show explicit
  unconfirmed copy and keep the write control locked until the relevant
  inventory (membership list or bot list) is refreshed by the user.

## Rate limits and abuse protection

| Route | BFF in-process limit | Authoritative upstream limit |
|---|---|---|
| POST /api/account-registration | 5/60 s per salted email hash + 20/60 s per process | Issuer registration IP/user limits |
| POST /api/session (login) | Existing 5/60 s per account | Issuer 5/60 s per account + 300/min shared ceiling |
| POST /api/tenant-creation | 5/60 s per salted credential hash | Issuer has no documented tenant quota (residual) |
| POST /api/bot-registration | Existing write lock | WebHook Redis 10/60 s per (user, tenant) |
| POST /api/bot-webhook-setup | 5/60 s per salted credential + bot | Backend per-bot claim, 60 s lease |

All new limiters are in-memory and per-process; a multi-instance deployment
needs a shared limiter and is out of scope. A 429 never triggers an upstream
call. Additional abuse protection: Host/Origin validation on every POST, no
CORS, bounded bodies, fixed error copy, and no token, secret, URL or email in
any response or log. The registration 409 inherently confirms an existing
email; that enumeration vector is an accepted residual until email verification
or CAPTCHA exist, consistent with the issuer's registration contract.

## Audit

No new audit store. The issuer records registration, login and tenant events
with its existing address-free subjects; WebHook Manager persists bot and
webhook rows with actor UUIDs and webhook state transitions. BFF logging stays
method/path/status/actor-ID only: emails, organization names, tokens, webhook
URLs and secrets are never logged. Browser-visible errors are fixed English
copy, never provider messages or exception text.

## UX states

1. Fresh account, empty organizations: explicit empty state distinct from
   pending and failed, with the "Create organization" control for any
   signed-in user.
2. Empty tenant, no bots: existing "No bots registered" state plus an owner CTA
   opening the existing registration form; members see the empty state without
   the CTA.
3. getMe rejection during registration (400): bounded "Telegram rejected the
   token" copy; the token field is cleared; fixing and resubmitting is a new
   user action. 409 explains the Telegram identity is already registered;
   429 asks to wait; 503 shows the unconfirmed/outage copy.
4. Unconfirmed outcome on any new write: explicit unconfirmed copy; the write
   control stays locked until the user refreshes the relevant inventory; no
   automatic retry anywhere.
5. Webhook states from the existing Bots projection: `not_configured`,
   `configuring`, `configured`, `failed`, `unknown`. Setup success shows
   `configured`; `failed` and `unknown` show bounded copy with an explicit
   retry as a new user action after refresh.
6. Access revocation or role change: scoped reads fail authorization as
   today; Refresh returns the possibly empty directory; owner-only controls
   disappear after the role change is reflected; session expiry returns to
   the existing sign-in screen with its sign-out-previous-session control.
7. Onboarding checklist, client-side only and derived from already-loaded
   safe reads: signed in; at least one organization; selected tenant has an
   active bot; stored webhook status `configured`; first reply pending with
   fixed copy explaining the operator activation dependency. It adds no
   request beyond the existing loads, never polls, never claims a total, and
   resets on tenant, section, Refresh and sign-out changes.

## Acceptance criteria

From `dashboard/` (new suites are also appended to the `npm test` list):

```powershell
npm test
node --test tests/account-registration.test.ts
node --test tests/tenant-creation.test.ts
node --test tests/webhook-setup.test.ts
npm run lint
npm run typecheck
npm run build
npm audit
```

Focused suites must cover per route: exact-field and duplicate/extra field
rejection, malformed and oversized bodies, unsafe Origin/Host, missing/expired
session where required, member and foreign-tenant denial before any upstream
call, CSRF attempt, limiter 429 without upstream, duplicate email 409, live
claim 409, issuer/backend outage and malformed or mismatched acknowledgements
as unconfirmed 502/503 without retry, and proof that no password, email,
token, webhook URL or secret appears in responses or captured logs. Existing
suites stay green.

Isolated fixture acceptance follows the 2026-10-29 records' pattern: a fresh
UUID Compose project with the production dashboard build, real AuthFortress,
WebHook Manager and PostgreSQL; a Telegram MockTransport restricted to one
fictional token; the Telegram platform mode enabled only inside the fixture
with a synthetic HTTPS webhook origin routed to an owned internal receiver
that records setup effects. A person with no fixture knowledge then completes
in the browser: create account → sign in → create organization → register bot
→ see the active bot → pass the preparation check → run Setup → see the stored
`configured` status. Negative checks in the same fixture: member and
foreign-tenant denial, revoked membership, duplicate email, registration and
setup 429s, issuer outage with unconfirmed recovery through refresh, and a
live-claim 409. Browser checks at 1280 and 360 CSS pixels with zero console
warnings/errors and keyboard-accessible labels. Before/after preservation
fingerprints; only owned fixture containers stopped; nothing deleted. No real
Telegram, LLM or provider call; no main-stand mutation; no live first reply.

## Implementation slices

1. **Account sign-up (dashboard only).** `POST /api/account-registration` with
   its limiters and mappings, the sign-in screen form with repeat password,
   focused HTTP tests, fixture check that a browser-created account can sign
   in, and the dashboard README section. No other route changes.
2. **Organization creation (dashboard only).** `POST /api/tenant-creation`
   with its limiter and mappings, the empty-state control, confirmed-success
   first-page refresh and selection, focused HTTP tests, and fixture checks
   for empty-account creation, unconfirmed outcome recovery and the
   duplicate-name residual.
3. **Webhook setup and onboarding guide (dashboard only).**
   `POST /api/bot-webhook-setup` with its limiter and mappings, the owner
   Setup control, the client-side onboarding checklist, focused HTTP tests,
   and the full-chain fixture and browser acceptance described above.

Each slice ships the full command list green, its focused suites, isolated
fixture evidence and a fresh independent adversarial/security review before
merge, and confirms the repository's existing dashboard GitHub checks passing
on the pushed branch on both Windows and Ubuntu. No slice touches a sibling
repository, the root Compose file or any existing stand.

## Out of scope

- Public deployment, TLS/domain/proxy configuration, and any capacity or load
  guarantee.
- Live Telegram `setWebhook` against `api.telegram.org`, live LLM/provider
  activation and the first live reply: setup is accepted only against a
  synthetic receiver; live activation is separately authorized operator work
  per [telegram-ai-reply.md](telegram-ai-reply.md).
- Member invitations, owner transfer, tenant rename or deletion, bot
  deactivation/token rotation/reactivation UI, email verification, password
  reset, CAPTCHA, OAuth sign-up, 2FA enrolment UI and billing.
- Automatic session refresh, multi-instance shared BFF limiters, per-service
  Redis ACLs, EventPipe/PipeWatch changes, new dependencies, schema
  migrations and any change to sibling services.

## Contract assumptions to confirm before implementation

Not blockers; both are observable in the sibling OpenAPI during slice work.

- The exact AuthFortress register field bounds and success status. Both root
  smoke drivers send `{"email", "username", "password"}` and expect HTTP 200;
  the BFF trusts the status only and its local pre-bounds are deliberately
  broader guards, not replacements.
- The apply acknowledgement shape `{bot_id, tenant_id, webhook_url,
  webhook_status}` as documented in
  [telegram-ingress.md](telegram-ingress.md). If the running WebHook Manager
  revision differs, stop and re-baseline this spec against the service's
  OpenAPI instead of relaxing acknowledgement validation.
