# Read-only per-bot AI job metadata

Add AI jobs beside recorded Usage to inspect the existing AgentHub processing
metadata without running or retrying jobs. Reuse the same private Agent origin,
fresh tenant authorization and active-bot inventory. No provider calls, service
changes, dependencies, migrations, raw job content or business mutations.

## Contract and minimal design

- `GET /api/jobs?tenant=UUID&bot=UUID[&cursor=UUID]`: exactly one tenant/bot,
  at most one nonempty cursor, canonical lowercase UUIDs and no extra keys.
  Host/session/query guards precede upstream calls. Repeat issuer membership,
  then GET the existing AgentHub tenant/bot `/ai/jobs?limit=50[&cursor=UUID]`.
  AgentHub independently checks ai.read and fresh active bot context.
- Return tenant, bot and at most 50 safe items: job ID, input event ID, known
  state, nonnegative integer attempts and normalized created/updated UTC times.
  Omit provider/model, envelope, answer, chat/update IDs, claims, errors and all
  extras. Enforce strictly ascending canonical job IDs after the cursor, unique
  input event IDs and valid field types. Malformed pages fail closed.
- Preserve AgentHub's limit+1 pagination semantics: a full page may end with
  null; a nonnull next cursor is legal only for 50 items and must equal the last
  job ID. Do not impose the Bots API's different full-page cursor rule.
- Native AI jobs navigation reuses paged active-bot selection. Load jobs is
  explicit; First job page/Next job page operate separately from First bot page/
  Next bot page. Changing bot or parent scope/page/section/Refresh aborts and
  clears prior job pages; ignore late responses and expire shared session on401.
- Native controls, full wrapping IDs, UTC labels, fixed state/attempt metadata,
  distinct no request/empty/end/error states and desktop/360 px layout. These
  are stored job snapshots, not live execution, complete history counts or an
  observability event replay. No polling, retry, reconciliation or delivery UI.

## Acceptance

1. Existing36tests plus HTTP regressions prove scope/query guards, owner/member
   fresh auth, source failures/redaction, bounded fields/order/duplicate/malformed
   pages and both valid full-page cursor endings. All tsc/Biome/build/audits pass.
2. Fresh isolated actual Auth/WebHook/Agent fixture seeds 52 selected-bot jobs,
   other/foreign/empty scopes and all five states. Actual BFF proves50+2, cursor
   end, empty/foreign/inactive/expired reads and GET-only access. Job/bot/usage
   fingerprints and controlled provider counters must stay unchanged.
3. Production browser desktop/360 checks cover selector/load/both paginations,
   safe full metadata, empty/error/recovery, stale responses, scope reset and
   logout. Preserve existing resources/WSL/data; stop only owned processes and
   retain their data. Record reproducible commands/results/limits/screenshot.
4. Fresh independent adversarial/security review, scoped commit/push and exact
   Windows/Ubuntu CI. No actual job execution or real providers are required.

Safe default: show safe metadata for one active bot, ordered by existing UUID
cursor contract. Historical time search and raw provider/job details need a
separate reviewed contract.
