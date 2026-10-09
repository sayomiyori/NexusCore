# Legacy delivery publication recovery

Status: source and isolated runtime verified on 2026-10-09; fresh
adversarial/security review approved. Root runtime rollout remains separate.

## Contract

- PostgreSQL is authoritative for pending, failed and manually retrying deliveries.
- Persist HTTP retry due time separately from notification retry due time. Keep
  public delivery fields and payloads unchanged; preserve existing HTTP backoff
  and MAX_DELIVERY_ATTEMPTS.
- Initial publication failure must not prevent later subscription intents from
  being persisted. Publish best effort with bounded broker waits and no hidden
  transport retries; keep the API event loop responsive and log static codes
  and UUIDs only.
- Confirmed HTTP failure persists the next attempt and due time before optional
  notification. Retry publication failure leaves that intent recoverable.
- A separate scanner works without Celery beat. Claim at most 100 due rows using
  PostgreSQL FOR UPDATE SKIP LOCKED, commit a 60-second notification lease before
  publication, stop on broker failure, scan every five seconds. Expired leases
  recover both failed publications and scanner crashes. Broker outages never
  consume HTTP attempts. Notification duplicates are allowed; HTTP claims remain
  serialized and respect the durable retry due time.
- Never recover success, exhausted or delivering rows. Delivering and ambiguous
  external effects require operator reconciliation; no exactly-once promise.
- Add a forward Alembic migration, backfilling only recoverable legacy states.
  Test upgrade/down/up on isolated synthetic PostgreSQL, preserving payloads,
  statuses, attempt numbers and terminal/active claims.

## Acceptance

Reproduce initial and retry publication failures before implementation. Cover
manual retry timing, initial/retry recovery, repeated and concurrent scanner
runs, expired publication leases, bounded batches, early task replay, preserved
terminal/active states and HTTP attempt exhaustion. Use real isolated PostgreSQL
and Redis; retain existing signature/header filtering tests. Run the full suite,
Ruff, strict Mypy, migration roundtrip/model check and a built-image worker/scanner
smoke. Fresh read-only adversarial/security review precedes scoped commit/push.

No live traffic, production data changes, unrelated refactors or new dependencies.
