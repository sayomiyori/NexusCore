# Tenant Overview acceptance — 2026-10-23

Scope: the first opt-in read-only Dashboard Overview. Only NexusCore's new
`dashboard/` package, its specification, checks and documentation are changed.
Sibling repositories, shared deployment configuration and WSL are outside this
change. No real Telegram/LLM, provider workers or root activation.

## Implemented

- Next.js App Router UI with AuthFortress sign-in, existing 2FA challenge,
  tenant selection, manual Refresh and issuer-aware logout.
- Server route handlers keep access/challenge credentials in short HttpOnly,
  SameSite=Strict cookies, Secure in production. Refresh tokens are discarded.
- Fresh issuer membership before scoped EventPipe/PipeWatch reads. A foreign
  tenant is denied before sink calls; no browser-supplied identity is trusted.
- At most ten safe recent observations across auth, webhook and AI sources,
  deduplicated by relay ID with independent receiver flags and full safe-content
  conflicts. Counts and timestamps explicitly describe observation snapshots.
- Bounded direct private HTTP transport, static errors, no proxy/redirect,
  no-store responses, nonce CSP, responsive layout and tested AA text contrast.
- SHA-pinned Windows/Ubuntu Node 24 CI. No new Python/sibling dependencies or
  migrations. Next/React supply the web runtime; TS/types/Biome supply checks;
  Node's built-in test runner avoids adding a test framework.

## Local automated evidence

From `D:/Programming/NexusCore/dashboard`:

```powershell
$env:NEXT_TELEMETRY_DISABLED='1'
npm ci
npm test
npm run typecheck
npm run lint
npm run build
npm audit
npm audit --omit=dev
```

Result: clean installation; 18 tests pass; strict TypeScript, Biome recommended
preset and optimized production build pass; both audit scopes report zero
vulnerabilities. Tests include login/2FA/logout contracts, cookie flags, Origin
and Host denial, foreign membership before any sink call, redaction, malformed
receiver types, conflicts, partial outages, response caps/deadlines and AA colors.

From `D:/Programming/NexusCore`:

```powershell
& .venv/tooling-checks/Scripts/python.exe -m unittest discover -s tests -p 'test_verify*.py'
& .venv/tooling-checks/Scripts/python.exe -m ruff check scripts tests
& .venv/tooling-checks/Scripts/python.exe -m compileall -q scripts tests
& .venv/tooling-checks/Scripts/python.exe -m pip check
git diff --check
```

Result: 131 root tests pass; Ruff/compileall/pip consistency and diff checks pass.
An existing FastAPI TestClient deprecation warning about httpx/httpx2 remains;
no dependency upgrade is included in this dashboard task.

## Review

Fresh independent adversarial/security review found three issues in the
unshipped draft: an inner unknown type could bypass outer-type consistency,
several small text colors had insufficient contrast, and Biome migration had
disabled its recommended rule preset. All three were fixed and independently
reproduced as resolved. A shared expiry handler also closes the pagination 401
UX edge. Final source review approved with no blocking findings.

## Isolated runtime and browser evidence

The original private fixture failed because a single SeaweedFS internal volume
slot was consumed by its default collection, leaving no slot for `raw-events`.
It was stopped and retained with a failed receipt. A fresh UUID fixture uses four
slots and verifies actual S3 bucket write/read before starting transform.

The second fixture, `nexus-dashboard-5f28e5dbd44343e48de4233c9d225712`, stored
three observations in EventPipe and three in PipeWatch. Its first harness pass
stopped at host-port discovery: Docker internal networks do not yield usable
published host ports. A temporary Windows loopback HTTP bridge forwarded bounded
requests through `docker exec` to the exact owned callback/API addresses. The
network remained internal. Product HTTP/session code was unchanged.

Resuming this fixture also exposed harness startup ordering: restored ZooKeeper
needed time to expire its old ephemeral broker registration before Kafka start;
transform started before SeaweedFS port 8333 was ready. Failed receipts remain
separate. Starting ZooKeeper first resolved broker registration; the exact owned
transform was restarted after confirmed S3 readiness. This is dashboard read
acceptance, not a claim of a fully unattended restart/restore drill.

Private commands from the root workspace:

```powershell
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/verify_dashboard_20261023.py
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/resume_dashboard_20261023.py
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/check_dashboard_preservation_20261023.py
```

These ignored, machine-specific acceptance drivers are receipts, not shipped
deployment tools. The first command's host-port discovery failure is documented
above. The resumed production HTTP/browser run passed:

- Actual issuer login and Secure/HttpOnly/Strict cookie attributes, without
  returning either access or refresh credentials in JSON.
- Three merged auth/webhook/AI observations, both receiver flags, safe projection,
  foreign tenant denial, issuer logout and revoked-credential rejection.
- Chromium production UI at 1280px and 360px; document widths 1265px/345px
  respectively, no horizontal overflow. Native keyboard Tab reached Sign out.
- Empty tenant, immediate clearing during tenant switches, HTML-looking tenant
  name rendered literally with zero image elements, account with no memberships.
- Owned EventPipe query stop: three PipeWatch-only observations and visible
  `1 / 2`/Unavailable state. Restore + Refresh returned `2 / 2`.
- Cross-tab sign-out: Refresh on the original Overview cleared observations and
  showed the expired-session sign-in message. Both browser sessions logged out.
- No unexpected console warnings/errors, CSP failures or hydration errors.

The final `dashboard-receipt-2.json` reports passed=true and all 14 fixture
containers stopped, no OOM; Python apps exited 0, Kafka/ZooKeeper 143 under
explicit SIGTERM. The host dashboard/bridge processes and listeners were closed.
Only synthetic fixture data was written; no real provider worker was started.

Preservation comparison against the task's original baseline passed exactly:
all 622 original containers, 343 volumes, 70 networks, images and protected files
remain unchanged; all 70 completed scanners remain stopped. Main SQL/schema/
sequences, uploads, container definitions, configuration and `.wslconfig` hashes
match. Both new attempts' data is retained: final inventory 650 containers,
363 volumes, 72 networks; only the original nine containers are running.

Private evidence: `.venv/dashboard-20261023-{main,resources}-{before,after}.json`,
`.venv/dashboard-20261023-preservation.json`,
`.venv/dashboard-browser-20261023.json`, and the separate fixture receipts.

![Verified synthetic tenant Overview](images/dashboard-overview-2026-10-23.png)

## Limits

No complete audit history, cost totals, business editing, registration/OAuth,
refresh workflow, public deployment or main-stack activation is claimed. Current
browser origin policy is numeric loopback only. Remote HTTPS/proxy deployment is
separate work; service API availability is not comprehensive live health.
The 2FA/backup-code exchange is covered by issuer-contract HTTP tests; a real
authenticator device and OAuth providers were not exercised in this fixture.
