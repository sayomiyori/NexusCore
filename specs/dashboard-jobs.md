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
  explicit; First job page/Previous job page/Next job page operate separately
  from First bot page/Previous bot page/Next bot page. For the loaded successful
  bot page, bot-page navigation reuses the visited-cursor history already used
  by Bots, Usage and AI Configuration: Next pushes the page being left, Previous
  pops it and First clears it, each only after a successful non-aborted bot-page
  read, capped at 50 entries with the oldest dropped. First is unavailable on
  the first loaded bot page and Previous only when no earlier bot page was
  visited. A failed bot-page read clears the loaded page, so the AI jobs section
  unmounts and only the page-level error and global Refresh remain; Refresh
  returns to the first bot page. Changing bot or parent
  scope/page/section/Refresh aborts and clears prior job pages; ignore late
  responses and expire shared session on401.
- Job page navigation keeps a visited-cursor history and a separate attempted
  action. The history stores the cursor of each page left behind, capped at 50
  entries with the oldest dropped, and it is pushed, popped or cleared only after
  a successful non-aborted read: Next pushes the page being left, Previous pops,
  First clears. A failed read keeps the last successful position and
  visited-cursor history but clears the displayed rows, and offers Previous and
  a Retry job page control that re-issues only that same attempted read. First
  stays available while the retained successful cursor is nonnull (even when the
  failed attempt was itself First) or the failed attempted cursor is nonnull.
  Next is offered only from a successful page's next cursor, and
  every job navigation control is disabled while a read is in flight. No cookie
  or API contract changes: the fresh `GET /api/jobs` call and its cursor rules are
  unchanged.
- Native controls, full wrapping IDs, UTC labels, fixed state/attempt metadata,
  distinct no request/empty/end/error states and desktop/360 px layout. These
  are stored job snapshots, not live execution, complete history counts or an
  observability event replay. No polling, delivery retry, reconciliation or
  delivery UI; the Retry job page control only repeats a failed read.

## Loaded-page state filter

Add a client-side state filter over the job snapshots already loaded on the
current page. It makes no API call, does not change `GET /api/jobs` or its cursor
rules, and never claims a tenant-wide or cross-page count.

- The control is a "Job state" select inside a fieldset whose legend is
  "Filter loaded job snapshots", with options for all states plus the five known
  stored states.
- Filtering preserves response order, leaves the loaded page and its next cursor
  unchanged, and does not alter First/Previous/Next/Retry, their abort behavior
  or their history transitions. The count reads matching of loaded rows on this
  page only.
- A zero-match filter with rows present is the distinct "No jobs in this state"
  state; the existing no-request, empty and end states stay unchanged.
- The filter is kept when moving between job pages and resets when the bot
  changes; parent scope, tenant, section and Refresh changes already remount the
  section and therefore reset it too.

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
