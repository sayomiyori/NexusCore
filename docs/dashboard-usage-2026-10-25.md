# Per-bot recorded Usage acceptance — 2026-10-25

## Implemented

Usage adds a read-only dashboard section backed by AgentHub's existing scoped
usage API. The active-bot selector reuses the existing 50-record Bots cursor
pages. Native date inputs specify a positive interval of at most 31 UTC days:
start inclusive, end exclusive, initially the current UTC day. Load usage is
explicit. Bot/date changes abort and clear old results; Refresh, organization,
section and bot-page changes reset the form.

`GET /api/usage` validates canonical scope/dates and fresh issuer membership
before AgentHub, which independently checks ai.read and current active bot
context. The new server-only Agent origin uses the existing bounded private
transport. Only safe integer counts and exact eight-decimal estimated USD leave
the BFF. Decimal/scientific forms use integer arithmetic, with no floating point
rounding. Errors never become zero totals. No provider/model/message/raw usage
fields, prices, billing operations or AI activation were added.

See [contract](../specs/dashboard-usage.md) and [runbook](../dashboard/README.md).

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

**36/36 tests passed**: the previous 29 plus seven usage HTTP cases covering
safe projection/GET headers, real UTC/leap/calendar bounds, malformed/duplicate
queries, fresh owner/member authorization, denial before source access,
zero/scientific/high-precision Decimal values, unsafe counts and source/origin
failures. Strict TypeScript, Biome (27 files), production build and both audits
passed; **0 vulnerabilities**. A test-only formatting error after adding the
member case was fixed and Biome rerun successfully; all 36 tests had passed.

A fresh independent read-only adversarial/security review repeated the suite,
strict type check, lint and audits. Additional independent probes covered nine
calendar and thirteen Decimal edge cases. Actual AgentHub route/SQL contracts
were checked directly: tenant AND bot filtering, >=start/<end, fresh issuer and
active bot context. Compiled client code contained the new Usage UI without
server-origin/transport/authorization modules. No open code/security finding.

## Actual isolated service acceptance

Namespace `nexus-usage-8c3ee08a886a412e8c6523a0d2825de5` used six cached-image
containers: PostgreSQL, durable Redis, controlled callback, AuthFortress,
WebHook Manager and AgentHub. All were new, on one internal network without
published ports or workers. Existing migrations ran only in new databases.
Only bot registration/read and AgentHub read feature flags were enabled;
Telegram ingress/replies, AI processing and all external credentials stayed off.
No image pull/build, real provider request or existing deployment change.

Synthetic data included 52 bots in the selected organization (49 inactive),
empty/inactive-only organizations and a foreign owner/tenant/bot. Six synthetic
completed jobs/usage rows included exact start/end boundary records, a separate
bot and a foreign tenant. No job was actually processed by an LLM.

Actual production BFF checks through real issuer/WebHook/AgentHub APIs passed:

- Selected UTC day returned **2 records / 40 input / 60 output /
  `0.12345679` estimated USD**. The exact-start record was included; exact-end
  and before-start records were excluded.
- Another bot returned its separate **1 / 999 / 999 / `99.00000000`**. An empty
  bot returned successful zeros and `0.00000000`.
- Foreign tenant was denied before Agent access; foreign bot and inactive bot
  were rejected. Issuer logout invalidated reuse; POST returned 405.
- Bot, webhook, job and usage table fingerprints and controlled provider counters
  matched before/after. All dashboard resource bridge requests were GET.

Actual Chromium checks passed:

- Explicit load and exact totals; desktop screenshot below. Bot page navigation
  showed 50 + 2 and cleared results without requesting new Agent usage totals.
- Successful zero and separate-bot totals, immediate clear on bot/date changes,
  native keyboard date edits and explicit error for an invalid zero-day interval.
- A two-second delayed old Agent request completed after changing the bot; its
  result did not reappear. Controls remained usable after abort.
- Stopping only owned AgentHub cleared prior totals on Load and showed an error,
  with no fabricated zeros. Starting that exact container restored the expected
  result. Empty/inactive-only organizations had no active selector or totals.
- At 360 px, four native tabs wrapped in two columns without horizontal overflow;
  date controls, full bot ID and exact money cards fit. Viewport reset afterward.
- Refresh and rapid section switches reset the form. Cross-tab issuer logout
  followed by Load showed the session-expired sign-in screen. Captured warn/error
  console entries were empty; no CSP/hydration issue observed. Test tabs closed.

![Actual synthetic per-bot Usage](images/dashboard-usage-2026-10-25.png)

Private ignored commands/receipts retained for this machine-specific acceptance:

```powershell
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/verify_usage_20261025.py
# Production browser checks, then finish marker after logout.
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/check_usage_preservation_20261025.py
```

Runtime `receipt.json` passed; all six owned containers stopped with exit 0 and
no OOM. The dashboard host/bridges closed and port 58909 had no listener.

## Preservation and limits

All **681 baseline containers / 375 volumes / 77 networks** match exactly,
including runtime state; images and protected files match. Full main SQL schema/
row/sequence, upload, container definition and root environment/release/WSL
fingerprints match. Six retained owned containers/three volumes/one network give
final **687 containers / 378 volumes / 78 networks**, 50 unchanged images,
70 completed scanners stopped and only the original nine containers running.
Foreign README/hardening WIP was preserved. Nothing was deleted.

This verifies synthetic recorded usage, not real provider pricing, billing,
tenant-wide aggregation, live AI, job execution, public HTTPS deployment, full
scanner smoke or an unattended restore-drill. Member projection is covered by
HTTP fixtures; the actual issuer/browser run used an owner account.
