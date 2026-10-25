# NexusCore dashboard

Opt-in tenant Overview, Bots and Events using existing AuthFortress, WebHook Manager,
EventPipe query and PipeWatch HTTP contracts. Overview displays up to ten recent
safe observations and authorized receiver availability. Bots displays a paged
configuration inventory. Snapshots are not current bot health or lifetime totals.
This package does not start or modify the root deployment.

## Run locally

Use Node.js 24 and npm. First prepare a separate isolated service fixture with
synthetic accounts and events. Expose only its AuthFortress, EventPipe query and
PipeWatch and WebHook Manager HTTP APIs on unused `127.0.0.1` ports. An `internal` Docker network does
not provide usable published ports; keep it isolated and use a bounded local
docker-exec HTTP bridge for that fixture, as in the acceptance record. Never use the main deployment's
environment file or enable provider workers for dashboard verification.

In PowerShell, from `dashboard/`:

```powershell
npm ci
Copy-Item .env.example .env.local
# Set the four service origins to the isolated fixture's actual loopback ports.
# DASHBOARD_ORIGIN must match the browser URL, including its port.
npm run dev
```

Open `http://127.0.0.1:3000` and sign in with an account created in that fixture.
Select an authorized organization and switch between Overview and Bots. Refresh
returns to the first page. Bots uses Next page/First page and up to 50 records
per response, without claiming a total. Names, activity flags and stored webhook
states come from scoped configuration reads; no live Telegram health request is
made. The views have no business mutation controls or automatic polling.

Events inspects the same ten merged observations as Overview, with full event/
bot IDs, UTC times, receiver evidence and observed attempt counts. Kind,
receiver, attention and ID filters combine locally without extra requests.
They apply only to the loaded window; Reset filters restores that window.
Refresh, organization and section changes reset filters. This is not historical
search or a complete audit log. Receiver names/statuses distinguish partial and
unavailable reads; conflicting snapshots are explicitly marked.

To check and run the optimized build:

```powershell
$env:NEXT_TELEMETRY_DISABLED='1'
npm test
npm run typecheck
npm run lint
npm run build
npm audit
npm start
```

Production mode uses Secure cookies. The local acceptance uses Chromium's secure
loopback handling; an eventual remote deployment requires a separately reviewed
HTTPS/origin/proxy configuration. Current browser origins intentionally allow
only numeric IPv4 loopback, not public hosts or forwarded headers.

## Boundaries

- Access and temporary 2FA credentials stay in HttpOnly, SameSite=Strict cookies.
  The server discards refresh credentials; access cookies expire after 15 minutes.
  Sign in again when the issuer session expires. Existing issuer rate limits,
  2FA/backup codes and membership authorization remain authoritative.
- Each Overview request checks current issuer membership before any sink query.
  Every sink request carries that identity and canonical tenant scope. No shared
  user cache, sibling imports, database access or secret-bearing browser config.
- Each Bots request repeats issuer membership before the WebHook Manager read.
  The BFF validates tenant, UUID ordering/cursors, active flags, known webhook
  states and dates. Bot and organization names follow their backends' 128
  Unicode code point limits.
  Tokens, ciphertext, Telegram identifiers, usernames and webhook URLs are
  excluded. Tenant/section changes clear prior data and abort stale reads.
- Server-only origins accept explicit numeric private/loopback HTTP(S) addresses.
  Direct requests ignore proxies, reject redirects and have bounded JSON sizes
  and five-second absolute deadlines. Wrong Host/Origin mutations are rejected.
- Only the existing three observation types are supported. The browser receives
  fixed labels, safe states, canonical IDs, timestamps and receiver evidence.
  Raw payloads, logs, previews, request/answer/provider data never reach the UI.
- Unavailable or malformed receivers are shown explicitly. A successful query is
  not a comprehensive health check. Differing safe content for a relay UUID is
  shown as conflicting evidence. Unknown event types can occupy a recent window;
  older supported observations are not scanned automatically.
- Organization pages contain up to 50 memberships. Tenant switches clear prior
  observations and abort stale reads. Logout clears cookies and requests issuer
  revocation; failures say when issuer sign-out could not be confirmed.

No registration, OAuth, refresh workflow, bot/AI editing, costs, Telegram alerts,
public deployment or main-stack activation in this increment.

Contract: [dashboard-overview.md](../specs/dashboard-overview.md).
Bots contract: [dashboard-bots.md](../specs/dashboard-bots.md).
Events contract: [dashboard-events.md](../specs/dashboard-events.md).
Verification: [Overview acceptance](../docs/dashboard-overview-2026-10-23.md),
[Bots acceptance](../docs/dashboard-bots-2026-10-25.md),
[Events acceptance](../docs/dashboard-events-2026-10-25.md).

![Verified synthetic tenant Overview](../docs/images/dashboard-overview-2026-10-23.png)

![Verified synthetic tenant Bots](../docs/images/dashboard-bots-2026-10-25.png)

![Verified synthetic recent Events](../docs/images/dashboard-events-2026-10-25.png)
