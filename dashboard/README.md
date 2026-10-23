# NexusCore Overview

Opt-in tenant Overview using existing AuthFortress, EventPipe query and PipeWatch
HTTP contracts. It displays up to ten recent safe observations and authorized
receiver availability. Snapshots are not current bot health or lifetime totals.
This package does not start or modify the root deployment.

## Run locally

Use Node.js 24 and npm. First prepare a separate isolated service fixture with
synthetic accounts and events. Expose only its AuthFortress, EventPipe query and
PipeWatch HTTP APIs on unused `127.0.0.1` ports. An `internal` Docker network does
not provide usable published ports; keep it isolated and use a bounded local
docker-exec HTTP bridge for that fixture, as in the acceptance record. Never use the main deployment's
environment file or enable provider workers for dashboard verification.

In PowerShell, from `dashboard/`:

```powershell
npm ci
Copy-Item .env.example .env.local
# Set the three service origins to the isolated fixture's actual loopback ports.
# DASHBOARD_ORIGIN must match the browser URL, including its port.
npm run dev
```

Open `http://127.0.0.1:3000` and sign in with an account created in that fixture.
Select an authorized organization; use Refresh to request a fresh observation
window. The view has no business mutation controls or automatic polling.

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
Verification: [acceptance record](../docs/dashboard-overview-2026-10-23.md).

![Verified synthetic tenant Overview](../docs/images/dashboard-overview-2026-10-23.png)
