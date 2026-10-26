# Persisted tenant and bot AI settings

Add durable model selection to the existing Telegram AI path, with tenant default
and per-bot override. Provider remains Groq (the only implemented platform
provider); credentials, prompts and processing activation remain operator-only.
No legacy RAG changes, main rollout, real providers or existing data mutations.

## Storage and effective behavior

AgentHub owns one current-settings table keyed by authorized tenant, target
(`tenant`/`bot`) and subject UUID; tenant subjects must equal their tenant.
Store nullable model (inherit), positive revision, actor UUID and UTC timestamp.
Append an immutable audit revision in the same transaction for every successful
write. No business DELETE. Null resets inheritance without losing revision/audit.
Validate model identifiers as in the existing configuration read.

Effective precedence: explicit bot model > tenant model > operator platform
model. All storage reads/updates filter tenant and target/subject. The first job
claim freezes this model; retries retain frozen provider/model. Saving settings
does not claim/run jobs or enable processing. No real provider is used in tests.

Add one forward migration from the clean published platform head002; never
edit applied002 or the original checkout's uncommitted003_tenant_resources.
The two migration lines need an explicit future merge before any deployment
combining that unrelated WIP. This task only migrates fresh owned test databases.

## HTTP contracts

- New GET/PUT `/api/v1/tenants/{tenant}/ai/settings` and
  `/api/v1/tenants/{tenant}/bots/{bot}/ai/settings`. Existing `/ai/configuration`
  remains unchanged for compatibility.
- Fresh issuer authorization on every read (`ai.read`, owner/member) and write
  (`ai.configure`, owner only). Exact matching receipt permission and owner role
  are checked independently. Bot routes also resolve fresh active bot context.
  No local JWT trust, client role or body scope. Denial precedes DB access.
- PUT JSON only, <=16KiB/5s, strict duplicate-free object with exactly `model`
  (valid identifier or null) and `expected_revision` (strict int0..2147483646).
  Reject extras/flags/provider/credentials. Atomic create-if-revision0 or
  compare-and-swap update; stale/concurrent write409, no partial audit. Commit
  before response. No automatic retry; lost receipt requires reload.
- GET/PUT200 returns canonical tenant_id, bot_id(nullable), target, saved
  `{model,revision,updated_at}`, effective `{scope,provider,model}` and operator
  processing_enabled. Unset saved row revision0/time null. Safe explicit fields,
  no actor identity or audit text. Fixed errors, no settings/credential dumps.
- Dashboard adds GET/PUT `/api/ai-settings?tenant=UUID[&bot=UUID]`, leaving the
  current BFF `/api/configuration` compatible. Exact query/Host/session guards;
  PUT also Origin/body guard, fresh owner check and upstream authorization.
  Existing private bounded transport supports explicit PUT and safe409 mapping.

## UI and acceptance

AI Configuration supports tenant default (even without bots) and active bot
override using the existing paged inventory. Explicit Load precedes editing;
owner gets model field, Save and Use inherited model; member sees read-only.
Show saved/effective scope/model, processing flag and revision. No activation
control. Conflict requires reload; ambiguous save clears stale result and says
reload before retry. Do not abort/hide an in-flight write through input changes;
disable form/scope/navigation while saving, and discard results after unmount.

Test narrow contracts then complete suites: fresh owner/member/foreign/revoked/
inactive/outage and malformed auth; strict input/CSRF; actual PostgreSQL CAS,
two-writer conflict, audit atomicity, inheritance/reset/independent bots/tenants,
first claim vs retry freezing, migrations up/down/up and alembic check. Verify
actual isolated issuer/WebHook/Agent APIs and production browser desktop/360,
reload/restart persistence, error/conflict/expiry/reset and preservation hashes.
Independent fresh adversarial/security review precedes scoped commits/pushes
in both repositories. Inspect exact-SHA CI and record commands/results/limits.
