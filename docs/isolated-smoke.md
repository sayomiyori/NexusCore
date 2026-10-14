# Isolated local smoke and scanner acceptance

Use the existing WebHook Manager virtualenv and locally cached service images:

```powershell
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_stack.py
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_telegram_ai.py
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_telegram_ai.py --scanners
```

The AI command runs its controlled chain, stops it, then runs a separate
standalone fixture. `--scanners` uses the real permanent recovery CLI entrypoints
in both fixtures. The standalone scanner can also be checked alone:

```powershell
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_stack.py --scanners
```

Each command owns a new `nexus-smoke-<uuid>` Compose project, private internal
network and new PostgreSQL/Redis/uploads volumes. It reads no root `.env`, needs
no external test database, publishes no host ports, pulls/builds no images and
makes no real provider/Telegram/OAuth calls. Default image IDs describe the
verified local release; another compatible cached release can be selected with
`--auth-image`, `--webhook-image`, `--agent-image`, `--postgres-image` and
`--redis-image`. No credentials are needed from the main deployment.

The callback is addressed by its inspected numeric IP. HTTP probes execute
inside its owned container and reject targets outside the inspected allowlist,
redirects and inherited proxies. Telegram/Groq effects accept only fixed
synthetic credentials; the actual issuer, bot/tenant authorization, migrations,
PostgreSQL, Celery and service handlers remain in the path. Only fixture AI
flags are enabled. MCP and real provider credentials remain closed.

## Permanent scanner checks

| Process | Real entrypoint | Recovery authority |
| --- | --- | --- |
| Ingress | `scripts.recover_platform_outbox` | WebHook ingress outbox |
| AI jobs | `scripts.recover_telegram_jobs` | AgentHub durable jobs |
| Reply publication | `scripts.recover_telegram_replies` | AgentHub reply outbox |
| Telegram send | `scripts.recover_telegram_answers` | WebHook send intents |
| Legacy delivery | `scripts.recover_legacy_deliveries` | WebHook delivery intents |

Scanner mode exercises actual long-running loops; one-shot recovery is forbidden
in the AI driver. The fixture briefly stops PostgreSQL and requires a fresh
recovery warning from every scanner while its container ID/start time remains
unchanged. Each loop also receives a broker outage with pending work and must
observe its enqueue failure without exiting. PostgreSQL and Redis then recover
without recreating their storage.

For jobs/replies/send, the appropriate scanner creates a notification while
its consumer is stopped. The driver stops that scanner, consumes only those
owned synthetic queue messages and starts consumer+scanner. Durable rows must
then advance through the actual recovery loop. Exactly one generation, usage,
result and canonical send must remain. Ingress deliberately loses its first
successful admission receipt; replay publishes the same job on attempt two.
Legacy delivery admits and deduplicates while Redis is stopped, then recovers
exactly two signed callbacks. Invalid HMAC/API-key access stays 401; exhausting
the configured fixture quota returns 429 without Redis. A second API process
shares that quota and restoring Redis keeps the 429.

Each scanner uses `init: true` and bounded `on-failure:2`. The harness kills only
its inspected `python -m <scanner>` child and requires an automatic restart of
the same container with a changed start time and increased restart count. Extra
cycles must not repeat provider/send/delivery effects. Application UID10001,
expected migration heads, running/no-OOM state and owned cleanup are checked.
Normal mode keeps its original closed settings and does not start scanners.

The current isolated WebHook image adds PostgreSQL legacy quotas. Its two local
migration heads (`8f3b1c6d2a90`, `c42d8e91a730`) are both checked; the separately
publishable WebHook source has the single new `c42d8e91a730` head. Fixture startup
uses `alembic upgrade heads`; no main deployment migration is performed.

Each new fixture assigns a UUID-derived private `10.x.y.0/24` subnet and verifies
it in Compose and Docker inspection. This avoids exhausting Docker's automatic
address pools while preserving stopped fixture networks/volumes. A conflicting
existing subnet fails fixture creation; no Docker/WSL setting is changed.

Every exit disables restart for inspected owned scanner IDs before stopping
owned containers, then checks stopped state and `restart=no`. Cleanup can be
retried; active checks still require the original bounded restart policy. If
disabling restart fails, cleanup still attempts to stop its own project and
reports failure. Volumes are retained for inspection.
Duplicate instances of one fixture service fail ownership validation before any
cleanup mutation; no scanner can be silently omitted from policy demotion.
The credential-free result is `.venv/nexus-smoke-<uuid>/receipt.json`, including
source hashes, checks, process proof and cleanup status. Captured command/log
errors are withheld from the CLI to avoid exposing credentials. Local receipts
and operational integrity snapshots are ignored and are not published.

## Retained fixture cleanup failure on 2026-10-14

Starting an already stopped Docker Desktop revived 23 retained synthetic
scanner containers even though their receipts recorded successful stop. Their
`on-failure:2` policy remained configured; scanner SIGTERM cleanup exits 143.
The inspected test scanners were demoted to `restart=no` and stopped without
deleting volumes or touching main containers. The lifecycle regression now
requires policy demotion before stop, rejects disabled policies during active
verification, and checks repeated cleanup and stop-after-update-error behavior.
It also rejects duplicate service instances before changing or stopping them.

Initial cleanup acceptance did not restart shared Docker/WSL. Runtime inspection
verified the persisted disabled policy. Main rows/schema/sequences/metadata, uploads and
configuration/WSL hashes matched the retained snapshot after Docker startup;
the same main container IDs/images were retained. Container fingerprints changed
across startup, so a separate post-start baseline was saved without replacing
the previous snapshot and is checked before/after further isolated work.

## Explicit Docker Desktop restart on 2026-10-14

At the user's explicit request, the retained completed scanner inventory was
checked around an actual Desktop/engine restart. All 35 scanners remained stopped
with `restart=no`; their container IDs, last start/finish times and restart counts
were unchanged in repeated post-start inspections. This includes stopped
containers from failed smoke runs and the separate publishable-source fixtures.

`docker desktop restart --timeout 180` failed during startup: the backend could
not remove the inaccessible `docker-secrets-engine/engine.sock` IPC object.
The two runtime directories containing only zero-byte reparse-point sockets
(`docker-secrets-engine` and `Docker/run`) were renamed
to adjacent preserved backups; Docker Desktop was relaunched normally. Its
session changed and all nine existing main containers restarted with the same
IDs/images/configuration/mounts. Six configured healthchecks became healthy,
both Celery workers logged fresh readiness without tracebacks and the main legacy
scanner remained idle. No factory reset, WSL shutdown/configuration change,
manual migration, data restore or volume deletion was performed.

PostgreSQL rows/schema/sequences/metadata, uploads and root configuration/WSL
hashes matched the pre-restart snapshot. All 224 volume names were retained.
Redis db1 retained its 17 logical values and absolute expiry times. Strict
whole-Redis equality failed for db2/db3: each still contains three Celery binding
sets, but its aggregate hash differs. The pre-start digest does not identify
individual changed members. Kombu's installed queue binding and generated pidbox
reply queue code is consistent with worker startup changing this metadata; this
is an inference, not proof of an exact member-level diff. No Redis restore was
attempted. Docker also reassigned runtime network endpoint IDs/MACs/IPs and the
default bridge network ID; static container configuration and mounts matched.

The scanner policy is verified across this real restart. Native unattended Docker
restart failed in this run; successful startup required the preserved-directory
recovery. Local credential-free before/after receipts
are retained under `.venv`; no live Telegram/LLM or load acceptance was performed.

## Docker IPC fix and native restart acceptance on 2026-10-14

Docker Desktop 4.63.0 aborted startup when Windows rejected stale host socket
access/removal with error 1920. Read-only directory enumeration identified
`engine.sock`, `dockerInference` and `userAnalyticsOtlpHttp.sock` as zero-byte
AF_UNIX reparse entries (`0x80000023`). These attributes do not establish NTFS
corruption or a kernel defect. The installed AF_UNIX driver was already running.

The official updater offered 4.95.0 (242831), consistent with the later successful
normal stop/start report in [Docker issue 554](https://github.com/docker/desktop-feedback/issues/554).
Before updating, read-only main/scanner/data fingerprints and per-key Redis
value/absolute-expiry hashes were saved; Desktop settings were backed up with
Windows DPAPI. `docker desktop update --quiet` installed the signed Docker Inc
release. Its old CLI process exited 1 during the update, so that exit is not
reported as successful; the installed signed binary, installer launch record,
running Desktop and subsequent native restart results establish the applied
version. Engine/CLI are 29.8.2 and Compose is 5.6.0.

Two consecutive `docker desktop restart --timeout 180` commands then exited 0.
Each changed the Desktop session and all nine main container start times while
preserving their IDs/images/configuration/mounts. No manual or external scripted
IPC cleanup, process kill, Windows reboot or WSL shutdown occurred during these
restart checks. Six healthchecks became healthy; host `/health` on 28080, 8001,
8014 and 8080 returned 200, both workers logged readiness without tracebacks and
the main legacy scanner remained idle. All 35 completed smoke scanners retained
their IDs/start/finish times/restart counts, stayed stopped and kept `restart=no`.

Main PostgreSQL rows/schema/sequences/metadata, uploads, `.env`/release/WSL hashes
and all 224 volume names matched the pre-update baseline. Redis db1 retained all
17 values and absolute expiries. Per-key comparison now proves the broker-only
difference: one existing Celery binding set value changed in each of db2/db3;
their three-key inventories, types and expiry semantics were preserved. No keys
were added/removed and no data restore was performed.

The data disk junction still targets `D:/Docker/wsl/disk`. WSL version and the
Windows AF_UNIX driver hash are unchanged. Existing explicit Desktop preferences
matched except the updater's `SettingsVersion` migration; it added install-time
metadata and `WslEngineEnabled=true`, recording the already used WSL backend.
No `.wslconfig` or distribution configuration was edited. No real Telegram/LLM
was enabled. Forced termination, sleep/resume, Windows reboot and load remain
outside this acceptance. Private backups and receipts are not published.

## Regression commands

On 2026-10-14, offline legacy admission and recovery passed with the updated
WebHook image: 202/200 while Redis was stopped, HMAC/API-key denials, shared 429
quota before/after broker recovery and two callbacks after scanner recovery.
The same API container is also stopped and restarted while Redis is unavailable.
Probes re-inspect its IP because Docker may reassign it. Live remains 200, ready
reports database OK/Redis unavailable with 503, the saved event returns its
original duplicate ID, HMAC stays enforced and exhausted quota stays 429.
The separate publishable-source runtime passed with its single new migration
head and one callback. Its full service suite passed 351 tests (85.86% coverage),
migration up/down/up/check, Ruff and strict Mypy. Twenty-eight root regressions
and fresh read-only adversarial/security review passed. Original root integrity
matched the before-task snapshot; all new test containers were stopped.

The later lifecycle continuation on 2026-10-14 passed the combined scanner
command on the final source hashes. The controlled AI fixture retained one
generation/usage/send; the separate legacy fixture retained two callbacks and
passed API restart with Redis unavailable. All 23 new containers stopped without
OOM and all five scanner restart policies were `no`. Twenty-nine root tests,
Ruff, compilation and fresh read-only adversarial/security review passed.
All nine main container IDs, start times and restart counts remained unchanged
during these tests; available healthchecks were healthy. Main data, uploads,
definitions and configuration/WSL hashes matched the post-start baseline.

Local acceptance on 2026-10-13 passed the combined scanner command: four AI loops
and the separate legacy loop recovered from PostgreSQL/broker faults and five
process failures. One controlled generation/usage/send and two legacy callbacks
remained. All 23 fixture containers stopped without OOM; scanner CLI exits 143 on
explicit SIGTERM cleanup are expected, while the other processes exited 0.
Twenty-seven root tests, Ruff, compilation and independent read-only review
passed. Original root data/uploads/container/configuration and WSL hashes matched
the retained integrity baseline. Local operational snapshots are not published.

```powershell
../WebHook_Manager/.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_verify*.py' -q
../WebHook_Manager/.venv/Scripts/python.exe -m ruff check scripts/verify_stack.py scripts/verify_telegram_ai.py tests
../WebHook_Manager/.venv/Scripts/python.exe -m py_compile scripts/verify_stack.py scripts/verify_telegram_ai.py
```

These checks do not certify live Telegram/provider quality, production capacity,
public TLS/OAuth/VPS or cross-host disaster recovery. Scanner faults are limited
to new synthetic fixtures; existing deployment data and WSL settings are outside
this workflow. Unknown external effects must never be automatically resent.
