# Shared observability flow acceptance — 2026-10-22

The new [metadata relay](observability-flow.md) passed actual isolated AgentHub
to EventPipe and PipeWatch delivery. No sibling repository, existing deployment,
WSL setting or real Telegram/LLM was changed. Source SHA-256:
`45d6a55c6182cf749c949c209c1b777756f8a142ef72d0c122dbcb723a5ee2c3`.

## Successful fixture

Project: `nexus-events-5e84bd21245843d7bc843cadc1642e7b`.
The private driver `.venv/verify_observability_20261022.py` exited 0; its retained
receipt reports `passed=true`, `owned_stopped=true`, `external_calls_enabled=false`.

Fourteen containers shared one new UUID-owned internal network without host
ports: PostgreSQL, Redis, AuthFortress, WebHook bot registry, AgentHub metadata
API, controlled setup/probe helper, Kafka, ZooKeeper, SeaweedFS, EventPipe
ingest/transform/query, ClickHouse and PipeWatch. No provider or Telegram worker
ran. All images were cached and resolved to immutable IDs; no build/pull occurred.

| Application | Image.Id |
| --- | --- |
| AuthFortress | `sha256:65256cebecb84ac274ad7726bcc12286ea8464f22651a2748f37f07dd45c5a6a` |
| WebHook / probe | `sha256:7cae10258f593cf22149130b306181ce26fa910542b96dc60582be9c333634d4` |
| AgentHub | `sha256:2daa64d236fe947f52498260a852ea402a4f2fd74ffbc9d033da67a1c80c8b03` |
| EventPipe ingest | `sha256:1515da1f10ece8f9d9808a0e9f0386a5fc9b49b901884fc6520380d2b4f6fee8` |
| EventPipe transform | `sha256:96d1425230f9f39371c76a2e052ec2d098893dc5fc0d7e097e881d95116e95f8` |
| EventPipe query | `sha256:b9fcaf30de38ff42b4d82fab018343f62f13ee8343ad9d8ab6bb9c74ed1b0421` |
| PipeWatch | `sha256:f9e8941bcbe4f948dcc4a8c070cb71ded8e401d1e5a31c1b79c48b4a1376139f` |

Fresh PostgreSQL databases were migrated with the cached applications. Real
AuthFortress registration/login created the owner and two tenants; bot
registration used the existing synthetic-only Telegram setup boundary. A
synthetic completed job with private answer/provider/model sentinels was inserted
only into the new AgentHub database. No generation or send was executed.

| Check | Actual result |
| --- | --- |
| Source | Actual authorized AgentHub job read; canonical bot context through WebHook/issuer |
| First relay | Two accepted per-sink deliveries, zero pending/unknown |
| Repeat process | Still two accepted deliveries; one stored event/log in each sink |
| EventPipe | Actual Kafka → transform → PostgreSQL/S3; authorized raw S3 bytes contain the same envelope |
| PipeWatch | Actual Redis backlog → ClickHouse; metadata equals EventPipe payload; trace ID equals relay UUID |
| Privacy | No private answer/provider/model sentinel or JWT in the envelope |
| Missing/invalid scope | No bearer rejected; nonexistent tenant rejected |
| Authorized tenant B | EventPipe event/raw 404; PipeWatch 200 with zero logs; source bot A under B rejected 404 |
| Partial failure | Stop only owned ingest, observe a new failed job version: PipeWatch accepts, EventPipe becomes unknown |
| After recovery/repeat | Three accepted, one unknown; EventPipe still one row, PipeWatch two; no automatic resend |
| Logout | Actual AuthFortress logout 204, then source authorization blocks relay before further delivery |
| Cleanup | All fourteen stopped, no OOM, restart `no`; twelve exit 0, Kafka/ZooKeeper exit 143 |

The relay ran as separate subprocesses inside the owned probe container. JWTs
arrived through stdin and child process environment, never command argument
values, console output or relay state. Fixed scripts were bound read-only;
SQLite state stayed inside the retained new probe filesystem. Container/image/
network/volume ownership was checked before lifecycle and SQL. Named local
volumes covered every image-declared Kafka/ZooKeeper mount.

## Commands and root checks

```powershell
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/verify_observability_20261022.py
& .venv/tooling-checks/Scripts/python.exe -B -m unittest discover -s tests -p test_verify_observability.py -q
& .venv/tooling-checks/Scripts/python.exe -B -m unittest discover -s tests -p 'test_verify*.py' -q
& .venv/tooling-checks/Scripts/python.exe -B -m ruff check --no-cache scripts tests
& .venv/tooling-checks/Scripts/python.exe -m compileall -q scripts tests
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/capture_stack_smoke_root.py .venv/observability-20261022-main-before.json
```

Thirteen focused tests passed. Full root regression: 105 tests OK in 35.317 s;
independent reviewer: 105 OK in 34.935 s. Ruff, compilation and scoped diff checks
passed. New tests use real SQLite and controlled HTTP boundaries, including
concurrent claims, state reopen, source/pagination/body/schema failures, safe
diagnostics, partial sink delivery and persisted unknown outcomes. No service
schema migration or dependency change was needed.

## Retained attempts and preservation

Four earlier preparations failed and remain distinct from successful acceptance:

| Project suffix | Containers retained | Reason |
| --- | ---: | --- |
| `1d6b40a68b8349a7ad49401936e6f809` | 6 | Missing verification-helper import mount; fixed before next attempt |
| `601ac652cf774108b1e67b526bf4fc55` | 10 | Strict ownership guard rejected new anonymous Kafka/ZooKeeper volumes; subsequent config names all mounts explicitly |
| `b0bee3c448dc4e4da3fa924b6699c99d` | 10 | ClickHouse health command needed escaped Compose dollar expansion; fixed and asserted in resolved config |
| `0950e7821c804ff69cb1792f4a7c61a7` | 14 | Functional pipeline passed, but logout expected 200 instead of actual 204 and ingest default CLI did not drain |

The final fixture uses the existing ASGI lifespan and the actual logout contract.
See [the ingest shutdown diagnosis](ERRORS.md#2026-10-22-cached-eventpipe-dual-cli-did-not-finish-on-http-shutdown).
All failed-attempt containers are stopped without OOM. One early WebHook process
exited 1 on its missing helper; fourth-attempt ingest exited 137 without OOM.
These exits were not accepted as successful cleanup. New anonymous volumes from
the rejected attempt were verified absent from the original inventory and
attached only to that new project before its exact containers were stopped.
Nothing was deleted, including these volumes and failed receipts.

Final inventory comparison preserved every original **526 container, 270 volume,
network/image/protected-file record and all 70 completed scanner states**.
Main PostgreSQL rows/schema/sequences/metadata, uploads/content/modes, nine
container definitions and `.env`/release/WSL hashes matched before/after.
Safe all-container inventory used `--size=false` and batches of at most 100 IDs.

Across all attempts, 54 new containers, 43 new volumes and five internal networks
were retained. All new containers are stopped with restart `no`; final totals
are **580 containers, 313 volumes, 70 stopped scanners, only nine original
containers running**. No original root service was restarted or recreated.
Snapshots/receipts stay private under ignored `.venv`.

## Limits

This connects the first observed AI-job stream, not every service audit event or
every intermediate transition. It is not dashboard delivery, sustained load,
production/off-host observability or live provider acceptance. The existing root
was not activated. JWT renewal/service credentials and unknown-outcome operator
reconciliation remain explicit deployment work; accepted relay receipts do not
guarantee exactly-once storage in either backend.
