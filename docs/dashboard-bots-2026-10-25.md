# Tenant Bots dashboard acceptance — 2026-10-25

## Implemented

The existing opt-in dashboard now has native Overview/Bots navigation and a
read-only bot configuration inventory. Each page contains at most 50 records;
Next page and First page use the existing WebHook Manager UUID cursor contract.
Refresh and organization/section changes clear old data and reset the cursor.
No totals, automatic polling or business mutation controls were added.

`GET /api/bots` checks Host/session/query inputs, then repeats current issuer
membership authorization before any WebHook Manager call. The service receives
the same identity and canonical tenant header. The BFF validates scope, UUID
ordering, cursors, flags, known states and timestamps, and projects only safe
configuration fields. Telegram identifiers/usernames, credentials, ciphertext,
webhook URLs and extra upstream fields are excluded. Stored webhook status is
explicitly distinguished from live Telegram health.

The new server-only `DASHBOARD_WEBHOOK_ORIGIN` reuses the existing bounded,
direct, private-address transport. No dependency, migration, sibling service or
root deployment change was required. See [contract](../specs/dashboard-bots.md)
and [local runbook](../dashboard/README.md).

## Automated checks

Run from `dashboard/` with Node.js 24:

```powershell
$env:NEXT_TELEMETRY_DISABLED='1'
npm test
npm run typecheck
npm run lint
npm run build
npm audit
npm audit --omit=dev
```

- Existing 18-test baseline passed before implementation. Final suite: **25/25**.
- Strict TypeScript and Biome passed; final production build passed.
- Full and runtime npm audits reported **0 vulnerabilities**.
- Added HTTP source tests cover projection, 50-record cursor boundaries,
  empty/malformed/duplicate/out-of-order/mixed-tenant pages, authorization before
  source access, Host/session/query guards, source failures and GET-only reads.
- Independent review found an unshipped Unicode mismatch: JavaScript UTF-16
  length rejected valid 65–128 emoji names. The local name guard now counts code
  points, retaining a bounded string check. Regression tests accept 65/128 and
  reject 129. Other transport/credential bounds retain their existing semantics.

Run from the repository root:

```powershell
& .venv/tooling-checks/Scripts/python.exe -m unittest discover -s tests -p 'test_verify*.py'
& .venv/tooling-checks/Scripts/python.exe -m ruff check scripts tests
& .venv/tooling-checks/Scripts/python.exe -m compileall -q scripts tests
& .venv/tooling-checks/Scripts/python.exe -m pip check
```

**131 tests passed**; Ruff, compilation and dependency checks passed. Existing
FastAPI TestClient deprecation output was not treated as a new application error.

## Actual isolated API and browser acceptance

Five cached-image services ran in a new UUID namespace on an internal network:
PostgreSQL, Redis, controlled callback, AuthFortress and WebHook Manager API.
No published ports, provider workers, image pulls or builds were needed. Only
temporary loopback HTTP bridges exposed the owned fixture APIs to the production
dashboard process. WebHook bridge access was GET-only.

The accepted namespace was
`nexus-bots-50b55021c01247c5a8043b070f53cb29`. It contained synthetic identities,
two organizations and 52 bot records, including an inactive bot, all five known
stored webhook states, a 128-emoji name and an HTML-like name. One bot used the
controlled registration API; remaining records were seeded only in the new test
database with unusable synthetic credentials.

Actual production HTTP checks passed:

- Issuer login and Secure/HttpOnly/SameSite=Strict session cookies.
- Pages **50 + 2**, exact cursor/end behavior, all stored webhook states and
  Unicode128 projection; no credentials or source-only fields in returned JSON.
- Empty organization, missing session, foreign identity denied before the bot
  source call, issuer logout followed by rejected reuse, and POST rejected 405.
- Bot/webhook table fingerprints and controlled provider counters remained
  unchanged across dashboard acceptance; every WebHook bridge request was GET.

Actual Chromium checks passed:

- Overview/Bots navigation, First page/Next page, Refresh returning to page one,
  empty organization and account without memberships.
- Desktop and 360 px viewport without horizontal overflow, including the long
  Unicode name; HTML-like text remained text with zero injected image elements.
- Rapid tenant/section switches did not restore stale rows. Keyboard Tab reached
  Bots. Cross-tab issuer logout followed by Refresh cleared rows and displayed
  the session-expired sign-in screen.
- Stopping only the owned WebHook API cleared stale rows and showed the bounded
  error/Refresh state. Starting that same container and refreshing restored the
  list. This is source outage/recovery evidence, not a full restore-drill.
- A repeated production/browser pass after process interruption confirmed login,
  no-membership state, 50 + 2 pages, Unicode/escaping and logout. Its captured
  warning/error console entries were empty; no CSP/hydration error was observed.

![Actual synthetic Bots second page](images/dashboard-bots-2026-10-25.png)

The first two preparation attempts were retained, stopped and not counted as
passing acceptance: the helper incorrectly expected an ID in registration output,
then Windows subprocess encoding rejected emoji seed input. The third seeded
attempt initially raced host readiness. The helpers were corrected to use
`/auth/me`, explicit UTF-8 and bounded readiness handling. That exact seeded
third fixture was resumed without recreation. A later interrupted browser
process lacked its final receipt, so production HTTP/browser reads and final
integrity checks were repeated before closure.

The private, ignored helpers/receipts used for this machine-specific acceptance
are not shipped deployment commands:

```powershell
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/resume_bots_20261025.py
# Browser acceptance through the production dashboard; finish marker after logout.
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/check_bots_preservation_20261025.py
```

Final runtime receipt: `receipt-bots-completed.json`, `passed=true`, all five
accepted services stopped with exit 0 and no OOM. Browser and preservation
receipts are retained privately beside the original failed-attempt evidence.

## Preservation and limits

All original **650 containers and 363 volumes** remain. Three owned five-service
attempts retain their data: final **665 containers, 369 volumes, 75 networks and
50 images**. All 15 owned containers are stopped, exit 0, no OOM, `restart=no`;
all **70 completed scanners remain stopped**, and only the original nine
containers run. No fixture/deployment data was deleted.

Initial-to-final SQL schema/row/sequence fingerprints for all three main
databases, upload content/modes, protected files, root environment/release files
and WSL configuration match. Every original volume matches; all 641 originally
stopped container records match exactly. Across the process interruption, the
nine originally running containers acquired new start timestamps/network
fingerprints; one initial network ID is absent and a new built-in `bridge`
network ID is present. **Full initial runtime equality is therefore not claimed.**
The initiating lifecycle event was not established by this feature acceptance.
During the resumed acceptance, all 650 original container records, network/
volume inventories and full main-stack fingerprints remained exactly equal.

Foreign root README/hardening work is preserved and excluded from this change.
No real Telegram/LLM calls, WSL changes, main-stack rollout or destructive
maintenance were performed. The fixture intentionally leaves EventPipe and
PipeWatch unavailable: Overview reports unavailable receivers. This increment
does not claim a new full observability smoke, unattended restore, public HTTPS
deployment, real-provider readiness, OAuth/registration/device-2FA acceptance,
bot editing, AI configuration or complete usage/cost analytics.
