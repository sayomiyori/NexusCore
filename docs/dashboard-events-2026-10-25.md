# Recent Events explorer acceptance — 2026-10-25

## Implemented

Events is a third native dashboard section beside Overview and Bots. It reuses
the unchanged tenant-authorized `GET /api/overview` and its ten merged safe
observations. Local AND filters cover event kind, receiver, attention and
case-insensitive event/bot UUID substrings. Reset restores the loaded window;
Refresh, tenant and section changes clear filters and stale data.

Rows display full canonical IDs, UTC times, validated attempt counts and receiver
evidence. Named receiver statuses make partial failures explicit. Conflicting
snapshots are not presented as a confirmed state. No new route, dependency,
database, raw payload/log access, historical scan, polling or replay was added.
See [contract](../specs/dashboard-events.md) and [runbook](../dashboard/README.md).

## Automated verification

From `dashboard/`:

```powershell
$env:NEXT_TELEMETRY_DISABLED='1'
npm test
npm run typecheck
npm run lint
npm run build
npm audit
npm audit --omit=dev
```

**29/29 Node tests passed**, including the existing tenant/auth/transport/bot
HTTP cases and three new filter tests. The latter cover combinations, trimmed
uppercase ID queries, failed/unknown/conflicting attention, empty/reset values,
preserved ordering and frozen immutable source records. Strict TypeScript,
Biome (22 files), production build and both audits passed; **0 vulnerabilities**.

A fresh independent adversarial/security reviewer repeated tests, TypeScript,
Biome and audit. Review found one ambiguity before release: a receiver count
alone did not identify which source was unavailable. Named EventPipe/PipeWatch
statuses now distinguish both cases. Independent rendering checks covered
partial/empty/unavailable data, full IDs, UTC, attempts=0 and conflict evidence.
No new server authorization or transport boundary was introduced.

## Actual service and browser verification

Eight cached-image containers ran in a new internal UUID namespace: PostgreSQL,
Redis, controlled callback, AuthFortress, an exited EventPipe migration runner,
EventPipe query, ClickHouse and PipeWatch. No published ports, workers, image
pulls/builds, Kafka, S3 or real providers were enabled. Temporary loopback-only
docker-exec bridges exposed the exact owned Auth/query APIs; receiver bridges
accepted only GET.

Namespace `nexus-events-b732966f1cfb43e6b1af86e7f5ff292c` contained fresh synthetic
identities/tenants. Five EventPipe processed records were seeded directly in its
new migrated database; five PipeWatch records used its real scoped ingest API.
These made six merged observations across the three known event types, including
one receiver conflict and single-receiver evidence. This verifies real read APIs
and projection, **not a new Kafka/transform/relay ingestion acceptance**.

Actual production HTTP checks passed: real issuer login/cookie flags, six merged
rows and conflict, redaction, empty/foreign tenant denial before receiver reads,
logout/rejected reuse. A real issuer-created 128-emoji tenant also passed list
and scoped projection, confirming the separate Unicode tenant-name fix.

Actual Chromium checks passed:

- All six rows, full IDs, UTC/attempts and conflict explanation; desktop layout.
- Combined filters returned one row; attention returned four; no matches had a
  distinct state; reset restored six. **Source GETs stayed 25 and all bridge
  calls stayed 38** through the filter/reset sequence: zero extra HTTP calls.
- At 360 px, all three navigation buttons and full identifiers fit without
  horizontal overflow. The 128-emoji tenant also wrapped within the viewport.
- Refresh reset controls; empty and rapid tenant/section changes cleared stale
  data. Keyboard focus remained usable.
- Stopping only owned EventPipe query showed five rows with EventPipe unavailable
  and PipeWatch responding. Stopping both showed zero rows with both named
  unavailable, rather than a successful-empty assertion. Starting the same
  exact containers and refreshing restored six rows and two responding receivers.
- Cross-tab issuer logout followed by Refresh cleared Events and showed the
  session-expired sign-in screen. Captured warning/error console entries were
  empty; no CSP/hydration issue was observed. Viewport override reset, tabs closed.

![Actual filtered recent Events](images/dashboard-events-2026-10-25.png)

Private ignored commands/receipts, retained as machine-specific evidence:

```powershell
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/verify_events_20261025.py
# Production browser checks; finish marker only after logout.
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/check_events_preservation_20261025.py
```

Final runtime receipt `receipt.json` passed. EventPipe/ClickHouse fingerprints
and controlled provider counters matched before/after; every dashboard receiver
call was GET. All eight accepted containers stopped with exit 0 and no OOM.
The dashboard host and temporary bridges were closed.

The initial preparation namespace
`nexus-events-edf4b5bb88f84cddbf6e907979c6d931` was retained as a failure: its private
helper omitted the existing Redis durability options. PipeWatch correctly
rejected startup (exit 3); all eight containers were stopped, no OOM. The helper
was corrected to appendonly=yes, appendfsync=always and noeviction **only for a
fresh test namespace**. No existing Redis configuration was changed.

## Preservation and limits

All **665 baseline containers, 369 volumes and 75 networks** match exactly,
including runtime records. Main SQL schema/rows/sequences, uploads, definitions,
root environment/release files, foreign WIP and WSL hashes match. All 70 completed
scanners remain stopped and only the original nine containers run. Two retained
eight-container attempts give final **681 containers / 375 volumes / 77 networks**;
50 images remain unchanged. Nothing was deleted.

This is a local recent-window explorer. No new full scanner smoke, unattended
restore-drill, public deployment, real Telegram/LLM, complete audit history,
cost totals, arbitrary raw-log search or business editing is claimed.
