# AuthFortress and WebHook observations in the shared stream

Extend the existing opt-in NexusCore relay with two real authorized metadata
sources. Existing service implementations, deployment data, WSL and credentials
remain untouched. No global admin audit, legacy API-key events, raw messages,
names, IP addresses, user IDs, Telegram identities or secrets are exported.

## Source contracts

- Optional `--auth-origin`: `GET /api/v1/tenants/{tenant_id}` with the same owner
  JWT. Validate canonical tenant UUID, owner/member role and aware creation time.
  Emit `auth.tenant.observed`, bot scope null, with only tenant creation time and
  observed caller role. Correlation reference is the tenant UUID, not an auth
  session/trace. Occurred time is first local observation time. Identity derives
  from tenant and safe payload, not polling time or selected bot. Replays retain
  the original envelope/time in SQLite. This is not a login/membership audit;
  a repeated identical role snapshot does not create another event.
- Optional `--webhook-origin`: `GET /api/v1/tenants/{tenant_id}/bots/{bot_id}`.
  Require matching canonical tenant/bot UUIDs, strict boolean activity, known
  webhook status and aware updated time. Emit `webhook.bot.observed`, with only
  is_active/webhook_status and bot UUID as correlation reference. Identity
  includes scope, updated time and safe payload. Retain inactive observations;
  they are authorized registry reads, not permission to process AI traffic.
- Existing optional `--agent-origin` retains its job contract and exact event
  identity algorithm. At least one source must be selected. Tenant/bot arguments
  remain required for CLI compatibility, even in auth-only mode. New source
  origins enter the existing state identity binding; do not silently reuse a
  state file bound to a different source set. Default AI-only invocation/state
  remain backward compatible; no SQLite schema change or new dependency.

## Authorization and delivery

Each source independently authorizes every sweep. Only event types whose source
completed a fresh validated scan may drain pending rows. One unavailable or
denied source does not suppress independently authorized source observations.
An inactive bot may deny the AI read while allowing its registry observation.
All-source failure stops with static diagnostics; partial-source failure returns
nonzero and an additional `source_errors` count, without raw errors or metadata.
Existing successful output remains the same three pending/accepted/unknown keys.

Reuse the same store/claim/receipt rules and both sink mappings. EventPipe's
event_type and PipeWatch's fixed message must match the actual envelope type.
Null bot scope is omitted from EventPipe scalar metadata. Error severity covers
failed/unknown AI jobs and failed/unknown webhook configuration; other snapshots
are informational. Accepted/unknown rows are never automatically resent.

## Acceptance and implementation scope

Update root relay, its tests, runbook/spec and `.env.example` explanation only.
No sibling API change, migration, event hook, credentials or root rollout.
Test both mappings/allowlists, UTC/identity stability, strict/canonical scope,
redaction, optional CLI/source binding, independent source failures, inactive
bot reporting, per-source pending authorization, duplicate/concurrent delivery
and unchanged AI IDs/state compatibility. Existing root checks must pass.

Use a fresh UUID internal fixture based on the verified previous drill: actual
AuthFortress tenant/bot APIs, actual AgentHub metadata, EventPipe Kafka/PG/S3 and
PipeWatch Redis/ClickHouse. All three event types must arrive in both backends
with equal safe envelopes, repeat without duplicate records and deny tenant B.
Observe bot deactivation despite AI denial, webhook-status change, issuer logout,
sink outage/unknown and disabled external providers. Preserve every original
resource/main fingerprint; stop only new owned containers and retain their data.
Independent review/security pass, scoped commit/push and Windows/Ubuntu CI.

Observed snapshots can miss transient changes. Global authentication audit and
tenant-scoped ingress/delivery history need separate safe export contracts;
their global legacy APIs must not be used as a tenant event feed.
