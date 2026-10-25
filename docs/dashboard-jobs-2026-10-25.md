# Read-only AI job metadata acceptance — 2026-10-25

## Implemented

AI jobs adds a native dashboard section for one active bot's stored AgentHub
job metadata. Explicit Load jobs reads at most 50 snapshots. Bot inventory and
job pages have separate controls. Job pagination preserves the existing
limit+1 contract: a full final page may have a null cursor. Bot changes abort
and clear prior jobs; Refresh, organization, section and bot-page changes reset
the selector. Late responses cannot restore stale scope data.

`GET /api/jobs` validates exact canonical tenant/bot/cursor query fields and
Host/session guards before upstream calls. Fresh issuer membership precedes
AgentHub, which independently checks ai.read and active bot context. The BFF
projects only job/event UUIDs, known state, bounded attempts and UTC timestamps.
Ordered IDs, unique input events and cursor semantics are validated. No raw
envelope, answer, provider/model, worker claim or error detail reaches the UI.
No backend change, dependency, migration, worker or provider activation.

See [contract](../specs/dashboard-jobs.md) and [runbook](../dashboard/README.md).

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

**43/43 tests passed**, including six Jobs HTTP cases and a shared timestamp
regression. Coverage includes safe projection, 50+2 pages, full final 50-page,
empty/end cursors, malformed/duplicate/oversize/unordered pages, invalid dates,
query/Host/session guards, fresh owner/member authorization, denial before
source access and source/private-origin failures. Strict TypeScript, Biome
(31 files), optimized build and dependency audits passed; **0 vulnerabilities**.

Independent review identified a shared date-validation gap before shipment:
`Date.parse` normalized February 30 and April 31 into other days. A failing
regression reproduced it. The shared guard now checks the original local
calendar before UTC conversion, rejects year 0000/hour 24 and retains valid
leap dates, offset day changes and microsecond-input normalization. Details
are recorded in [ERRORS.md](ERRORS.md).

A fresh final read-only adversarial/security reviewer independently repeated
all 43 tests, type check, lint and both audits; checked the real AgentHub SQL/
authorization contract and century/year/offset date probes; inspected all three
acceptance receipts and documentation. Verdict: APPROVE, no open findings.
That reviewer did not repeat Docker/browser acceptance or the production build;
the builder ran those checks as recorded here.

## Actual isolated service acceptance

Namespace `nexus-jobs-02a826aaa08f4e69aa4f7d0610977635` used six cached-image
containers: PostgreSQL, durable Redis, controlled callback, AuthFortress,
WebHook Manager and AgentHub. All were new, on an internal network without
published ports or workers. Existing migrations ran only in new databases.
Only bot and AgentHub read features were enabled; Telegram ingress/replies,
AI processing and real credentials stayed disabled. No image pull/build.

Synthetic records included 52 selected-bot jobs, 50 other-bot jobs and one
foreign job, all five states, empty/inactive/foreign scopes and retained
synthetic usage records. No LLM processed these jobs.

Actual optimized BFF checks through the issuer/WebHook/AgentHub APIs passed:

- Selected bot returned **50 + 2**, then the final null cursor. Another bot's
  exactly 50 records correctly ended with a null cursor. Past-end and empty
  bot reads returned empty lists. All five states were displayed.
- Foreign tenant was denied before Agent access; foreign/inactive bots were
  rejected. Bot IDs remained disjoint. Issuer logout invalidated reuse and
  POST returned 405. Dashboard resource requests used GET only.
- Existing Usage retained **2 records / 40 input / 60 output / `0.12345679` USD**.
  Job, usage and bot fingerprints and controlled provider counters matched.

Actual Chromium checks passed:

- Owner login, explicit load, both page controls, 50+2 and full final 50-page,
  empty bot, full UUID/UTC/attempt metadata and safe projection.
- Desktop and 360 px layout; five navigation tabs wrapped without horizontal
  overflow and full IDs remained readable. Viewport reset afterward.
- A two-second delayed old request completed after changing bots; its result
  did not reappear. Bot-page changes, Refresh and rapid section switches reset
  prior jobs. Empty/inactive-only organizations showed no active selection.
- Stopping only the owned AgentHub cleared old rows on Load and showed a fixed
  error. Starting that exact container restored 50 rows. Cross-tab issuer
  logout followed by Load expired the workspace. Captured warn/error console
  was empty; no CSP/hydration issue observed. Created test tabs were closed.

![Actual synthetic AI job metadata](images/dashboard-jobs-2026-10-25.png)

Private ignored commands/receipts retained for machine-specific acceptance:

```powershell
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/verify_jobs_20261025.py
# Browser acceptance, then finish marker after logout.
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/check_jobs_preservation_20261025.py
```

Runtime `receipt.json`, browser receipt and preservation receipt passed. All six
owned containers stopped with exit 0 and no OOM; dashboard/bridge processes
closed. No existing fixture was stopped or deleted.

## Preservation and limits

All **687 baseline containers / 378 volumes / 78 networks** match exactly,
including runtime state. Images and protected files match. Full main SQL
schema/row/sequence, uploads, container definitions, root environment/release
and WSL fingerprints match. Six retained owned containers/three volumes/one
network give **693 containers / 381 volumes / 79 networks**, 50 unchanged images,
70 completed scanners stopped and the original nine containers running.
Foreign README/hardening WIP was preserved. Nothing was deleted.

This verifies stored synthetic metadata, not job execution, retries/recovery,
real Telegram/LLM, full scanner smoke, restore-drill or public HTTPS deployment.
Member access is covered by HTTP fixtures; the real issuer/browser used an owner.
