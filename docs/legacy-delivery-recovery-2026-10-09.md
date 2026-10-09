# Legacy delivery broker recovery verification

Date: 2026-10-09. Contract: `specs/legacy-delivery-recovery.md`.
Service: independent `D:/Programming/WebHook_Manager` sibling repository.
Released source: `4457c79ecea0bba8a8236517a74072e2c1612f14` on `main`, pushed
without force after tests and review. Root evidence is committed separately.

## Changed

The dispatcher previously committed a pending delivery and then let a broker
exception escape, skipping later subscriptions. The worker committed failed
state before Celery retry publication, which could fail independently. Two
regression tests reproduced both publication exceptions before the correction.

Forward migration `6e2f8a1c9b04` adds internal HTTP and notification due times.
Creation persists initial/manual retry schedules; confirmed failure persists
the next attempt and existing backoff before bounded best-effort notification.
PostgreSQL state now governs retries instead of Celery retry metadata. Worker
replays respect HTTP due time and preserve serialized delivery claims.

`scripts/recover_legacy_deliveries.py` runs independently of broker/beat, scans
every five seconds, leases at most 100 due pending/failed/retrying rows through
`FOR UPDATE SKIP LOCKED` and commits a 60-second notification lease before I/O.
It stops publication at the first broker error. Expired leases recover missed
publication, lost scanner work and unprocessed remainder without spending HTTP
attempts. Success/exhausted/delivering records are excluded. Broker publishing
has two-second socket/connect waits with transport retry disabled; DNS and
cumulative operations have no total two-second deadline.

No public schemas, payloads, settings or dependencies changed. API-created
pending and manually retrying records are now executable through the scanner.
The existing manual retry schedule and HTTP retry limit/backoff remain intact.

## Verified

Isolated tmpfs PostgreSQL at `127.0.0.1:59629`, Redis at `127.0.0.1:59630`;
builder DB `webhook_recovery_test`, reviewer DB `webhook_review_test`. Neither
test run uses root application data. From `D:/Programming/WebHook_Manager`:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://webhook_test@127.0.0.1:59629/webhook_recovery_test'
$env:TEST_REDIS_URL = 'redis://127.0.0.1:59630/0'
$env:DATABASE_URL = $env:TEST_DATABASE_URL
$env:REDIS_URL = $env:TEST_REDIS_URL
$env:CELERY_BROKER_URL = $env:TEST_REDIS_URL
$env:COVERAGE_FILE = 'D:/Programming/WebHook_Manager/.venv/recovery-builder.coverage'
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m pytest tests/integration/test_delivery_recovery.py tests/integration/test_worker_delivery.py tests/e2e/test_webhook_flow.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/ --cov=src --cov-report=term --cov-fail-under=80 --tb=short
.venv/Scripts/python.exe -m ruff check src/ tests/ scripts/ alembic/
.venv/Scripts/python.exe -m mypy src/ --strict
uvx --from pip-audit pip-audit --path .venv/Lib/site-packages --format json --output .venv/recovery-dependency-audit.json
uvx --from bandit bandit -r src/ -ll
git diff --check
```

Final builder suite: **347 passed**, one existing Starlette HTTP 413 deprecation
warning, **40.67 seconds, 85.78% coverage**. Builder/reviewer coverage files were
isolated after a shared-file conflict; the final run had no coverage warnings.
Ruff passed; strict Mypy passed for
119 source files. Recovery file: 18 passed, including committed real PostgreSQL
concurrency, skipping a held row lock without waiting, bounded batch progression,
manual retry due/execution, early notification suppression, replay, publication
lease recovery and terminal/active-state exclusions. Existing tests still verify
HTTP attempt exhaustion, signatures, header filtering, circuit behavior and
concurrent HTTP claims. Dependency audit found no known advisories; Bandit had
zero medium/high findings (one low finding).

On separate `webhook_migration_test`, a local ignored probe ran
`alembic upgrade 3cc3bb772105`, seeded ten synthetic legacy delivery rows,
`alembic upgrade head`, `alembic downgrade 3cc3bb772105`,
`alembic upgrade head` and `alembic check`. Original records, payloads, statuses
and attempt numbers were preserved. Manual schedules and five failure backoff
cases were correct; success/exhausted/delivering schedules remained null.
No model/migration drift. Local probe command:
`.venv/Scripts/python.exe .venv/recovery_migration_probe.py`, with DATABASE_URL
explicitly selecting the isolated migration DB. No applied migration was edited.

Independent fresh adversarial/security review used the separate review DB:
verdict **APPROVE**, full suite **347 passed in 40.34 seconds, 85.78% coverage**,
Ruff/Mypy passed, Alembic head/check passed. Updated narrow recovery/worker/E2E
suite: **34 passed in 24.75 seconds**. Reviewer used
`COVERAGE_FILE=.venv/recovery-review.coverage`; final coverage had no warnings.
An additional probe confirmed all batch leases commit before publication,
publication stops after its first failure, exceptions containing a synthetic
sensitive marker are not logged, crashed scanner leases expire/recover and no
HTTP attempt is consumed. A real TCP blackhole caused one connection and
OperationalError in 2.056 seconds. This is a scoped security review, not a clean
security bill for arbitrary legacy egress or the entire platform.

## Built-image acceptance

```powershell
docker build -f .venv/module-recovery.Dockerfile -t webhook-delivery-recovery:20261009 .
.venv/Scripts/python.exe .venv/recovery_smoke_probe.py
.venv/Scripts/python.exe .venv/recovery_smoke_resume.py
.venv/Scripts/python.exe .venv/recovery_smoke_repeat.py
.venv/Scripts/python.exe .venv/recovery_smoke_final.py
```

The ignored Dockerfile reuses `webhook-audit-base:20261009` and copies current
source, scripts and Alembic migrations. Built image ID:
`sha256:ab554e0bd43039a179f7aa7c09756fefd394b9539dd7dce05665a4ba3cff61e7`.
This is a source-overlay build using the existing audited dependency base.

Isolated Docker network `webhook-recovery-check`, synthetic smoke DB, its own
ephemeral Redis, prefork Celery worker and an internal-only HTTP receiver:
initial broker publication failed with pending intent preserved; scanner
published after broker recovery. The receiver held its first HTTP request until
the smoke broker was stopped, then returned 500. Worker saved attempt two and
its due time; retry publication failed safely. An unavailable-broker scanner
preserved a notification lease without spending an HTTP attempt. Recreated
broker/worker plus expired synthetic lease recovered the task; final status
was success, exactly two signed requests (500 then 200). Final scanner replay
submitted zero tasks. Synthetic due times were advanced explicitly to avoid
waiting through backoff; production schedules were untouched.

The first probe lost the worker warning because it read stdout only, while
Celery emitted it on stderr. After fixing the observer, the retained failed
state completed the chain successfully. This was a probe defect, not a source
fix. The complete chain was subsequently repeated on a fresh synthetic DB.

Review reproduced synchronous publication blocking the API event loop during a
broker outage. A deterministic regression failed before the correction.
Dispatcher now awaits `asyncio.to_thread(enqueue_delivery, ...)`; only immutable
UUID strings enter the thread, while the database session remains on its event
loop. An independent real blackhole probe with three subscriptions kept the
50 ms timer responsive at 65 ms (previously 2.061 seconds); all intents persisted.
The image was rebuilt and the full outage chain repeated after this correction.

## Release boundary and limitations

Stop old API/worker processes, migrate and deploy new API/worker/scanner together.
Old workers do not write durable retry due times. The scanner is required for
recovery; simply upgrading source does not supervise it automatically. README
documents the separate process commands, migration and operational warnings.

Root schema/image/Compose were **not upgraded**. Its retained API/worker image
is the previous delivery-claim checkpoint; rollout with schema/data rehearsal
remains a separate step. Root volumes, unrelated open-webui and live flags were
preserved. User WebHook changes `docker-compose.yml` and `.cursor/` are excluded.

Recovery covers already persisted delivery intents. A crash before background
dispatch creates them remains open. Delivering/ambiguous external outcomes need
manual reconciliation; automatic resend is prohibited. Endpoint-wide concurrent
failure counters, SSRF/egress policy, shared legacy tenant identity, VPS/domain,
live Telegram/provider traffic and sustained load were not verified here.
