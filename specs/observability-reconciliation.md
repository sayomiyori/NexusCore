# Read-only reconciliation of uncertain relay deliveries

Provide an explicit operator check for existing `unknown` EventPipe/PipeWatch
deliveries. Reuse the relay's CLI, bound scope, private origins, bounded HTTP,
owner JWT environment and safe diagnostics. No sibling change, new dependency,
deployment activation, POST, retry, receipt reset or local state mutation.

## Contract and assumptions

- `--reconcile` selects one GET-only report instead of collection/delivery.
  Require all original source/sink origins, tenant/bot and the existing state
  binding, but do not call sources: current sink tenant-read authorization is
  authoritative for historical observations, including inactive bots.
- Require explicit `--eventpipe-query-origin` in this mode. The operator must
  select the query API for the bound ingest deployment. It uses the same numeric
  loopback/RFC1918 origin validator. It is not part of the original SQLite
  binding, so existing identities remain compatible. Reject this option in
  normal delivery mode and reject interval reconciliation.
- Open existing regular SQLite state with `mode=ro`; never initialize/migrate it.
  Reject missing/link/nonregular paths and binding mismatch before HTTP. Trusted
  local parent directories remain required. Support the relay's default rollback
  journal; reject WAL format before SQLite opens to prevent shared-memory writes.
  Validate/reconstruct every selected
  saved envelope against the existing source builders, deterministic identity,
  exact canonical scope and safe schema before any query. Do not export it.
- Inspect at most 100 unknown per-sink rows, fail explicitly if exceeded. Ignore
  pending/accepted rows. All stdout is aggregate integer counts:
  `confirmed`, `unresolved`, `duplicates`, `conflicts`, `errors`.
  Exit 0 only when all selected unknowns are confirmed (or none exist); otherwise
  exit 1. CLI syntax stays exit 2/static diagnostics. Report never updates rows.

## Receiver evidence

- EventPipe: `GET /api/v1/events?source=nexuscore&page=N&size=100`, then
  `GET /api/v1/events/{canonical_storage_uuid}` for every listed row.
  Preview text is not evidence. One scan serves all EventPipe unknowns. Maximum
  10 list pages/1,000 summaries; a full last page fails as incomplete. Repeated
  storage IDs, inconsistent source/type/ID/schema, malformed/oversized responses
  or denied/unavailable endpoints fail that sink's checks. The scan must finish
  before reporting matches. A positive match requires the full saved envelope,
  source/type and relay metadata ID/bot scope to agree. Either payload ID or
  metadata relay ID claiming a target with different content is a conflict.
- PipeWatch: `GET /api/v1/logs?service=nexuscore&trace_id={relay_uuid}&page=1&size=2`.
  Require valid nonnegative strict total, page/size, consistent capped item count,
  canonical trace/service/type and complete metadata equality. A trace match or
  count alone cannot confirm delivery. Two or more matches report duplicates;
  differing content reports conflict. Backend count/page races fail closed.
- Exact JSON equality distinguishes bool/int and rejects non-finite numbers.
  Any conflicting candidate takes precedence over duplicate/confirmed; no match
  means unresolved, never proven absent. Sink read failures remain independent.
  List pagination can move under concurrent traffic; this report establishes
  observed presence, never uniqueness, a complete history or exactly-once storage.

## Scope, verification and risks

Change only the root relay, its tests and observability spec/runbook/evidence.
Test actual SQLite byte/schema/state preservation, GET-only method boundaries,
all three event types, complete equality/scope/identity, duplicates/conflicts,
empty/delayed results, auth failures, limits/pagination/transport/parser failures,
independent sinks, repeat/concurrent use and unchanged normal delivery behavior.
Run full root tests/lint/compile, fresh read-only adversarial/security review,
scoped commit/push and Windows/Ubuntu CI.

Use a new UUID internal Docker fixture for actual storage/query acceptance:
simulate lost receipts after real acceptance, compare reports with storage,
prove reconciliation repeats without new records or state writes, retain an
absent uncertain delivery as unresolved and test revoked/foreign authorization.
Preserve all original resource/data/config/WSL fingerprints; stop only owned new
containers and retain all data. No real Telegram/LLM or shared runtime changes.

Safe default: reporting only. Persisting a reconciliation decision or permitting
resend is separate work. Absence/delay, backend duplicates, token expiry and
explicit ingest/query pairing remain visible operator limitations.
