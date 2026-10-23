# Read-only uncertain-delivery acceptance — 2026-10-23

The explicit `--reconcile --eventpipe-query-origin ORIGIN` mode reports receiver
evidence for existing unknown deliveries. It performs only GETs, never calls
sources, resends or changes relay state. See the
[contract](../specs/observability-reconciliation.md) and
[runbook](observability-flow.md#read-only-unknown-reconciliation).

Tested relay SHA-256:
`c15166d9ce561d1c3f7689e9aee8df0a78112cfb1a28e04256b4a248856788eb`.

## Local checks

```powershell
& .venv/tooling-checks/Scripts/python.exe -B -m unittest discover -s tests -p test_verify_observability_reconciliation.py -q
& .venv/tooling-checks/Scripts/python.exe -B -m unittest discover -s tests -p 'test_verify*.py' -q
& .venv/tooling-checks/Scripts/python.exe -B -m ruff check --no-cache scripts tests
& .venv/tooling-checks/Scripts/python.exe -m compileall -q scripts tests
& .venv/tooling-checks/Scripts/python.exe -B -m pip check
```

New focused checks: **17 OK**. Final full root regression: **131 OK in 37.592 s**.
Ruff and compilation passed; pip check reported no broken requirements.
The suite emitted an existing Starlette/httpx deprecation warning; no dependency
was changed to suppress it.
Fresh read-only adversarial/security review: **APPROVE**. Reviewer independently
ran the 129-test suite before the final two test-only additions, then all final
17 focused tests, Ruff, compilation/pip checks and scoped diff checks. It
independently compared saved snapshots/receipt/source hash and the runbook;
it did not perform Docker lifecycle actions or repeat the actual drill.

The tests use real temporary SQLite and controlled HTTP boundaries. They cover
actual lost-receipt state from normal sends, byte/schema/state preservation,
read-only SQL enforcement, escaped URI paths, WAL/link/missing-state rejection,
all three source types, exact typed JSON, foreign scope/content, duplicate and
conflicting records, pagination and incomplete scan, malformed/oversized/nested
responses, timeout/auth errors, independent sinks, concurrent/repeated reads,
orphan/row limits, static CLI diagnostics and unchanged normal delivery behavior.

Fresh review found one defect in the unshipped draft: filtering summaries by
outer event type could hide a conflicting claim to the relay ID. The scan now
reads every listed NexusCore detail and the regression reproduces that case.
See [the diagnosis](ERRORS.md#2026-10-23-reconciliation-could-miss-an-id-claimed-under-another-outer-type).

## Actual Docker drill

Fresh project: `nexus-events-ad1cea79b70b45a2a46f768ed0060dd9`.
Private driver `.venv/verify_reconcile_20261023.py` exited 0; its retained receipt
reports `passed=true`, `owned_stopped=true`, `external_calls_enabled=false`,
with the same source hash above. No failed Docker attempt was required.

Fourteen new containers shared a UUID-owned internal network without host ports.
Cached immutable application images match the
[previous three-source drill](observability-identity-bots-2026-10-22.md).
The fixture used actual issuer/tenant/bot APIs, synthetic-only Telegram setup,
metadata jobs, EventPipe Kafka/PostgreSQL/S3 and PipeWatch Redis/ClickHouse.
No build/pull, real Telegram/LLM or provider worker ran.

An HTTP stream boundary consumed each real successful POST response, then raised
a synthetic read timeout before the relay could record its receipt. This caused
six unknown deliveries while both actual storage pipelines retained their three
observations. The wrapper counted methods and rejected any non-GET operation
during reconciliation. JWTs entered through stdin/process environment, never
argument values, output or relay state; scripts were mounted read-only.

| Check | Actual result |
| --- | --- |
| Lost receipt | Normal relay made six real POSTs and retained six unknown outcomes; each backend stored three records |
| First reconciliation | Six confirmed, zero unresolved/duplicates/conflicts/errors; seven GETs, zero POSTs |
| Repeat reconciliation | Same report, byte-identical SQLite/file set and unchanged backend counts |
| Normal relay repeat | Three source GETs, zero POSTs; six unknown outcomes remain unchanged |
| Safe evidence | All three envelope types match across EventPipe full payload, authorized S3 raw bytes and PipeWatch metadata; private sentinels/token absent |
| Foreign authorized tenant | EventPipe list 200/empty; PipeWatch 200/total zero |
| Missing evidence | Stop only owned ingest for a new failed job version: one accepted PipeWatch delivery, one additional unknown EventPipe delivery |
| After ingest recovery | Six confirmed, one unresolved; repeat changes no SQLite bytes or stored counts (EventPipe 3, PipeWatch 4) |
| Query outage | Stop only owned EventPipe query: three PipeWatch confirmations, four query errors; restoring query restores prior report |
| Foreign identity | Another actual issuer account cannot query selected tenant: seven errors, zero confirmations and zero POSTs |
| Revocation | Actual owner logout 204; next report has seven authorization errors without changing state |
| Stop | All fourteen stopped without OOM, restart=no; twelve exit 0 and Kafka/ZooKeeper exit 143 |

Final relay state deliberately remains **seven unknown, one accepted**. A
successful report confirms observed storage, not permission to rewrite that
state. Empty evidence remains unresolved; no reset, resend or clearing happened.

## Preservation and exact local commands

```powershell
& .venv/tooling-checks/Scripts/python.exe -B .venv/capture_reconcile_resources_20261023.py .venv/reconciliation-20261023-resources-before.json
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/capture_stack_smoke_root.py .venv/reconciliation-20261023-main-before.json
& .venv/tooling-checks/Scripts/python.exe -B .venv/verify_reconcile_20261023.py
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/capture_stack_smoke_root.py .venv/reconciliation-20261023-main-before.json
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/capture_stack_smoke_root.py .venv/reconciliation-20261023-main-after.json
& .venv/tooling-checks/Scripts/python.exe -B .venv/check_reconcile_preservation_20261023.py
```

Every original **608 container, 333 volume, 69 network, image and protected-file
record** matched, including all **70 completed scanner states**. Main SQL rows,
schema, sequences and metadata, uploads/modes, nine container definitions and
`.env`/release/WSL hashes matched; separately saved main snapshots are equal.
Safe inventory used `--size=false` and inspect batches of at most 100 IDs.
Bounded captured logs (3,000 lines/container) found no Python traceback.

The new fourteen stopped containers, ten local named volumes and one internal
network are retained. Final totals: **622 containers, 343 volumes, 70 networks,
70 stopped scanners and only nine original running containers**. No existing
resource was restarted/recreated/deleted and no WSL setting was changed.

The private driver/receipts/snapshots remain under ignored `.venv`; they are
local acceptance tooling, not a portable public Docker test suite. Committed
unit tests are the reproducible automated regression checks.

## Limits

The report establishes observed presence only. Offset pagination may move during
traffic; capped/inconsistent/denied scans fail closed. No negative delivery
proof, exactly-once guarantee, state-update procedure, production/off-host
acceptance or real provider test was added. Correct ingest/query pairing and
current authorized JWT provisioning remain explicit operator responsibilities.
