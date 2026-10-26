# Read-only platform AI Configuration

Expose the existing operator-managed Telegram AI settings for an authorized
active bot, then show them in the dashboard. This is shared platform policy,
not a saved per-bot override. No editing, credentials, key-presence probes,
provider calls, job execution, worker activation or deployment changes.

## Contract

- AgentHub adds `GET /api/v1/tenants/{tenant}/bots/{bot}/ai/configuration` under
  the existing opt-in read router. Reuse fresh issuer ai.read and active bot
  authorization. Return canonical tenant_id/bot_id, scope=`platform`,
  provider=`groq`, model (null if empty), processing_enabled boolean. Only these
  explicit fields; no settings dump, secret/credential readiness, URLs or prompts.
  This reports cached process settings, not a provider connectivity/readiness
  check. Disabled read feature remains 404. No database access is necessary.
- Model must be bounded nonempty ASCII model identifier syntax
  `[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}` when present; an empty configured value is
  null. Invalid source configuration returns a fixed 503, without its value.
  A disabled processing flag may coexist with a chosen model. Never infer that
  enabling a flag proves credentials or a worker are ready.
- Dashboard `GET /api/configuration?tenant=UUID&bot=UUID` rejects duplicate,
  extra and noncanonical scope fields, validates Host/session before upstream,
  repeats fresh issuer membership then reads AgentHub with the same bearer.
  Validate exact returned scope/IDs/provider/model/boolean; allowlist projection
  and existing bounded private transport. Failures are not an unconfigured state.
- Native AI Configuration section reuses paged active-bot selection, with
  explicit Load configuration. Display operator-managed shared scope, provider,
  selected model/unset state and processing flag. Explain that the flag is not
  readiness and no bot-specific policy is stored. No activation or edit control.
  Clear/abort on bot/scope/page/section/Refresh; ignore stale responses, shared
  session expiry on401. Distinct unloaded/loading/unavailable/empty selection.
- Preserve foreign WIP. Implement AgentHub's clean read-router change in an
  isolated branch from origin/main; never publish its existing local-only commit
  or WIP. Only fresh synthetic fixture data may be created; existing stands and
  WSL must remain unchanged. No new dependency/schema/config variable.

## Acceptance and plan

1. Backend endpoint tests exercise real authorization clients with HTTP boundary
   doubles: owner/member, missing/duplicate/revoked/foreign/inactive/outage,
   disabled feature, disabled/unset and chosen model, invalid config redaction,
   response allowlist and no DB/provider access. Ruff/Mypy/relevant suite pass.
2. BFF HTTP tests cover projection/IDs, malformed fields, guards/authorization,
   source failures and GET-only resource reads. Existing dashboard suite,
   TypeScript/Biome/production build and audits pass.
3. Actual isolated issuer/bot/backend acceptance and production browser desktop/
   360 checks cover scope, unset/chosen disabled settings, outage/recovery,
   stale replies, expiry/reset and no secret exposure. Prove fixture/main data
   fingerprints and provider counters unchanged; stop owned resources, retain data.
4. Fresh independent adversarial/security review; commit/push only verified
   changes in each repository, inspect exact-SHA CI and report limits.

Safe default: implement read-only shared settings now. Durable tenant/bot
overrides and editing require a separate storage/processor contract; a form
that stores disconnected preferences would falsely imply effective configuration.
