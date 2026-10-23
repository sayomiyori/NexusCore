# First tenant Overview dashboard

Build the first opt-in read-only product screen after the verified shared
observability stream. Independent sibling services remain unchanged. No root
rollout, deployment data/WSL mutation or real Telegram/LLM activation.

## Scope and architecture

An independent `dashboard/` Next.js App Router package uses existing AuthFortress,
EventPipe query and PipeWatch APIs through same-origin server route handlers.
Next/React provide the web runtime; TypeScript/types and Biome provide
strict compilation/lint. Biome avoids the current Next ESLint preset's peers
requiring the unsupported ESLint 9. Use Node's test runner and standard HTTP transports;
no UI kit, database, auth framework, client token store or extra validation
dependency is needed for this screen. Minimal runtime-validated dashboard DTOs
are allowlists, not replacements for sibling OpenAPI models.

Server-only origins must be explicit numeric IPv4 loopback/RFC1918 HTTP(S)
origins without DNS, credentials, paths, query or fragment. Direct HTTP(S), no
proxy/redirect, fixed paths, five-second absolute deadline and 256 KiB responses.
`DASHBOARD_ORIGIN` is the expected loopback browser origin; validate Host and
Origin on session POSTs. Do not load the root `.env` or use NEXT_PUBLIC secrets.
All dynamic API/page responses are private/no-store. Nonce CSP, no framing,
no sniffing/referrer or external fonts/scripts. No unsafe-inline scripts.

## Session and tenant authorization

- `POST /api/session` accepts only bounded JSON email/password, or a 2FA code.
  Proxy to existing issuer login/login-2fa routes; keep temp_token/access_token
  only in short HttpOnly SameSite=Strict cookies (Secure in production).
  Return success/challenge state, never either token or refresh credentials.
  Existing issuer rate limits and 2FA/backup codes remain authoritative.
- `DELETE /api/session` requires same-origin validation, requests issuer logout
  and clears local cookies even if revocation fails. Do not claim issuer logout
  succeeded when unavailable. No refresh/registration/OAuth flow in this increment.
- `GET /api/tenants?offset=N` queries the issuer's current membership list in
  bounded pages, returning only canonical UUID/name/owner-or-member role.
- `GET /api/overview?tenant=UUID` first reads canonical issuer tenant membership.
  Missing/expired credentials return 401; foreign tenant denies before any event
  request. Never trust tenant selection from browser alone. Every sink request
  includes the same bearer and canonical X-Tenant-ID; no cross-user cache.

## Overview evidence

Read EventPipe `source=nexuscore&page=1&size=10` and at most ten full details;
read PipeWatch `service=nexuscore&page=1&size=10`. Requests are independent after
issuer authorization. Validate list/page/UUID/body bounds, source/trace/type,
canonical tenant, schema version/time and allowlisted payloads for the three
existing observation types. Unknown event types are excluded; malformed known
types fail that backend rather than presenting a false empty state.

Return at most ten recent normalized observations, merged by relay UUID with
receiver evidence and explicit conflicts for differing safe content. Only fixed
kind labels, safe enum states/role, timestamps, attempt counts and canonical IDs
may enter the browser. No raw previews/log messages, request/answer/provider/model,
credential, free-form error or global audit output. Tenant name is an authorized
identity UI field, rendered as escaped text; do not log it.

Counts refer to the displayed observation window, never lifetime processing or
cost totals. Source availability means an authorized API response, not complete
service health. Observed bot/job states are historical snapshots. Handle loading,
empty, expired-session, partial-backend outage and conflicting evidence visibly.
Tenant switching must clear old data and ignore/abort stale responses.

## UI and acceptance

Login/2FA, available tenant selection/pagination, Overview cards, source-response
badges and recent observation list. No bot edits, AI settings, costs, public
deployment, automatic polling or dashboard links to unimplemented pages.
Use English UI/code/docs consistently. Keyboard labels/focus/status messages,
responsive 360px and desktop layout, AA contrast and reduced-motion support.

1. Node tests cover direct/bounded transport, private origins, session cookies,
   CSRF/Host guards, 2FA/logout, fresh membership and foreign denial before sink
   calls, payload redaction/escaping contract, conflicts/dedup and independent
   outages. Build, strict tsc, Biome, npm audit and original root checks pass.
2. New isolated UUID fixture creates synthetic accounts/tenants and all three
   real observation types. Dashboard reads actual issuer/EP/PW through new
   dedicated loopback fixture endpoints, without modifying existing resources.
   Docker internal networks do not publish usable host ports: use a temporary
   loopback-only docker-exec HTTP bridge to the exact owned callback/API IDs,
   rather than granting the fixture an external network route.
   Test cross-tenant/expired/logout and degraded reads, no business writes.
3. Browser checks actual login/Overview/logout at desktop and mobile, no console
   or hydration errors; verify HttpOnly/CSP/no local token storage. Review fresh
   adversarial/security context, preserve all original data/config/resource/WSL
   fingerprints, stop only new owned fixtures and retain data.
4. Scope commit/push and verify root/dashboard CI. Document local limits: no
   session refresh, partial recent windows, snapshot health and explicit private
   deployment configuration. Real providers and root activation stay disabled.
