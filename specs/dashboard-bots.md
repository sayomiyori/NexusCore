# Read-only tenant Bots dashboard

Extend the existing opt-in Overview with a Bots section for an authenticated
tenant member. Reuse the existing workspace shell, HttpOnly session, bounded
private transport, issuer authorization and English UI. No sibling changes,
business mutations, Telegram/LLM calls, root rollout or WSL/data maintenance.

## Contract and minimal design

- Add `GET /api/bots?tenant=UUID[&cursor=UUID]`. Reject unknown/duplicate keys,
  missing tenant, noncanonical UUIDs and an explicitly empty cursor. Host/session
  guards run before upstream access. Only GET is implemented.
- Reuse fresh AuthFortress `GET /api/v1/tenants/{tenant}` authorization before
  calling WebHook Manager. Do not trust the selector or cursor as authorization.
- New server-only `DASHBOARD_WEBHOOK_ORIGIN` follows existing numeric private
  origin/no proxy/no redirect/deadline/body-cap rules. Request
  `/api/v1/tenants/{tenant}/bots?limit=50[&cursor=UUID]` with the same identity and
  canonical tenant header. The existing issuer and service remain authoritative.
- Project only `{tenant, items, nextCursor}`. Each item contains canonical bot
  ID, escaped authorized name (1–128 Unicode code points), strict active flag, known stored
  webhook status and normalized created/updated timestamps. Validate tenant
  equality, strictly increasing IDs after cursor and at most 50 items. Require
  the upstream next cursor to match the last ID on a full page, else null.
  Discard Telegram identifiers/usernames, tokens, ciphertext, URLs and extra
  response fields. Malformed/mixed-tenant pages fail closed, never show as empty.
- Keep the existing single workspace URL with native Overview/Bots navigation
  buttons. Both real views share tenant selection, Refresh and logout. No new
  routing/auth framework or client data cache is required. Refresh and tenant/
  section changes reset to the first page, clear old data and abort stale reads.
  Forward cursor navigation and First page provide the complete bounded list;
  there is no invented total count or automatic polling.
- Clearly label active/inactive configuration and stored webhook status. A
  configured webhook is not a live Telegram health check. No create, deactivate,
  token, provisioning, AI configuration, cost or alert controls in this increment.

## Checks and acceptance

1. Establish the existing 18-test/build/lint baseline. Add Node HTTP tests for
   projection, pagination, malformed/duplicate/out-of-order/mixed-tenant data,
   auth/Host/query denial before any bot call, issuer/service failures and
   missing configuration. Prove every upstream call is GET and no credentials
   or source-only fields enter JSON. Existing Overview/auth tests remain green.
2. Strict TypeScript, Biome, production build, npm audits and relevant root
   checks pass. Update the dashboard example/runbook; no new dependency/migration.
3. Use a fresh isolated synthetic fixture, never an existing deployment's data.
   Actual issuer/WebHook API acceptance covers multiple cursor pages, inactive
   and known webhook states, empty tenant, foreign identity, service outage,
   recovery and logout. Verify that bot listing makes no Telegram request.
4. Browser desktop/360px checks cover navigation, tenant/section switching,
   pagination/Refresh, empty/error/session-loss states, escaped names, keyboard
   focus, no overflow/CSP/hydration errors and retained Overview behavior.
5. Fresh independent adversarial/security review, exact preservation receipts,
   stop only owned test processes and retain their data. Commit/push only this
   verified scope and confirm Windows/Ubuntu dashboard CI.

Safe assumptions: Bots is a read-only configuration inventory; the issuer's
owner/member read policy is unchanged. No blocking product question is needed.
Runtime availability is verified separately; earlier acceptance is historical.
