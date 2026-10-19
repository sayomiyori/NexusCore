# Isolated local smoke and scanner acceptance

For root tooling regressions without Docker or sibling repositories, use
[the standalone checks guide](local-checks.md). The GitHub Actions workflow
runs those checks on Windows and Ubuntu; service/scanner acceptance remains below.

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

Add `--load` for a bounded local HTTP baseline after the functional checks:

```powershell
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_telegram_ai.py --scanners --load
```

For each fixture, Auth `/health`, WebHook `/health/ready` and Agent `/health` run
sequentially for five seconds with four clients and a p95 gate of 500 ms. The
existing loopback-only probe runs inside each inspected owned API container;
its two source files are mounted read-only. No host ports or wider URL allowlist
are needed. `receipt.json` retains measurements/source hashes, including completed
measurements if a latency gate fails. Any load failure fails the fixture and
still stops owned containers. Default commands do not run the load stage.

Clients share the API container's resource budget. These short health/readiness
measurements do not establish production capacity, external-client latency,
business-operation throughput or a production SLO. See the
[load acceptance contract](../specs/isolated-load-smoke.md).

### Bounded load acceptance on 2026-10-19

Executed the combined command above after the ordered-teardown fix `9f41d4f`:
AI project `nexus-smoke-6461ec2d70874c6da8cc0231a219f3aa`, followed by standalone
project `nexus-smoke-b75968a01eec44a99457ff59b2c5c992`. Both receipts passed,
including the functional scanner/outage checks and final exit/OOM verification.

| Fixture | API | Requests | p95 ms | Maximum ms |
| --- | --- | ---: | ---: | ---: |
| Controlled AI | Auth health | 5,605 | 5.34 | 117.69 |
| Controlled AI | WebHook readiness | 2,536 | 12.56 | 167.73 |
| Controlled AI | Agent health | 4,312 | 6.44 | 14.24 |
| Standalone | Auth health | 5,101 | 6.56 | 63.34 |
| Standalone | WebHook readiness | 2,789 | 8.60 | 84.03 |
| Standalone | Agent health | 3,716 | 9.49 | 161.25 |

Each row is a separate five-second/four-client probe expecting HTTP 200. Source
hashes were `233e20328e5449b31a52b3ec3785d39e0a2bd29664d10ce6201b0efde1130ff3`
for `verify_local_load.py` and
`42fb1544d9078c0bc9c15bfa06681bfd8f3e812f163d50f041f18cecd9da6e96`
for `local_files.py`. The six p95 gates passed; these are local health/readiness
measurements, not production capacity or business-operation throughput.

The rerun preserved all 432 pre-existing containers, 245 volumes, networks,
cached images and 50 completed scanner states. All 23 new containers stopped
with `restart=no`, without OOM: five scanners exited 143, the other 18 exited 0.
Six owned volumes were retained. Main rows/schema/sequences/metadata, uploads,
nine container definitions and deployment/WSL configuration hashes were unchanged.
The initial 409-container/239-volume/45-scanner baseline was also preserved.

An earlier full run exposed a worker forced to exit 137 during parallel cleanup,
despite a successful receipt. That false-positive cleanup result was fixed and
separately rehearsed before this full rerun; see the
[recorded cause and fix](ERRORS.md#2026-10-19-smoke-receipt-accepted-a-worker-killed-during-parallel-teardown).
No historical receipt or test volume was deleted or rewritten.

## Existing metrics exporters and platform closures

Both smoke drivers now check `/metrics` after functional verification and before
optional load. Each request executes on container loopback inside an inspected
owned API, with a five-second socket timeout and a 1 MiB response limit. There
is no proxy, redirect or caller-supplied destination.

Standalone Auth, WebHook and Agent exporters must return HTTP 200, `text/plain`
and their existing required Prometheus `# TYPE` markers. In the controlled AI
fixture, Auth keeps its current exporter, WebHook must return its existing 503
denial and Agent its existing 404 denial. The denied responses must contain only
the known JSON `detail`; global metrics are not enabled to make the checks pass.

Receipts retain only status, export/denial state, required family names, byte
counts and the probe source hash. Raw response bodies, sample values and label
values are not printed or saved. This is endpoint/marker acceptance, not full
Prometheus grammar validation, a new monitoring deployment, tenant-safe metrics
aggregation or an event/log pipeline. See the
[metrics acceptance contract](../specs/isolated-metrics-smoke.md).

### Metrics boundary acceptance on 2026-10-19

The full `verify_telegram_ai.py --scanners --load` command passed again with
metrics enabled: controlled project `nexus-smoke-3a4e4a09350b45c49ed3afe118f4f133`,
then standalone project `nexus-smoke-8d6b9ee79aa84df29e2bf127bd72d4fb`.

| API | Standalone | Controlled platform | Required families checked |
| --- | ---: | ---: | --- |
| Auth | 200 | 200 | `auth_register_total`, `active_sessions_total` |
| WebHook | 200 | 503 | `webhooks_received_total`, `deliveries_total` only in standalone |
| Agent | 200 | 404 | `documents_total`, `chunks_total`, `llm_requests_total` only in standalone |

Both receipts record probe SHA-256
`7f5e1436cc1b3a9d1af48b2909cfd7d18c56b2ae50efbd35232d9791a1523e20`.
The six subsequent load gates also passed (p95 5.36–9.40 ms). All 23 new
containers stopped without OOM with restart disabled: 18 exit 0, five scanners
exit 143. Six owned volumes were retained.

The final comparison preserved every pre-existing 455-container/251-volume
record, all networks/images/protected files and all 55 completed scanner states.
Main database/upload/container/configuration and WSL fingerprints matched the
original baseline. Final inventory: 478 containers, 257 volumes, 60 completed
scanners, only the original nine containers running. No data was removed,
service source changed or real Telegram/LLM enabled.

### Full scanner smoke after tooling safety fixes on 2026-10-19

Repeated the complete scanner/load command on source `4ef0619`, after the CLI
privacy, raw-response limit and backup-input handle fixes:

```powershell
& ../WebHook_Manager/.venv/Scripts/python.exe -B scripts/verify_telegram_ai.py --scanners --load
```

The command exited 0. Controlled AI project
`nexus-smoke-115eb25a16e945d58d54a7de0593536a` and subsequent standalone project
`nexus-smoke-c229f7fcfded43bda96421a6ca3f3a65` both recorded `passed=true`,
`owned_containers_stopped=true` and `external_calls_enabled=false`.

The controlled chain retained exactly one generation/usage/reply/send after
PostgreSQL, broker and consumed-notification faults, a deliberately lost admission
receipt and all four automatic scanner restarts. Tenant/deactivation denials and
duplicate/conflict checks passed. Standalone upload/Celery/PostgreSQL, login/JWT,
API restart without Redis (live 200, ready 503, durable quota/event/HMAC), two signed callbacks and the
fifth scanner restart passed. Metrics remained 200/503/404 for controlled platform
and 200/200/200 for standalone.

| Fixture | API | Requests | p95 ms |
| --- | --- | ---: | ---: |
| Controlled AI | Auth health | 5,877 | 5.15 |
| Controlled AI | WebHook readiness | 2,608 | 12.17 |
| Controlled AI | Agent health | 4,251 | 6.62 |
| Standalone | Auth health | 5,170 | 6.44 |
| Standalone | WebHook readiness | 2,763 | 9.36 |
| Standalone | Agent health | 3,821 | 8.17 |

Each load probe used four clients for five seconds, HTTP 200 and the 500 ms p95
gate. Both receipts match current source hashes:
`cdeead2db31666854b022beeb0721e04035bbf26c65f4e29c00ef04f38392e96`
for `verify_local_load.py` and
`99abae4e27f1558b1353251c0c80e71b6027873713b6e7b4f6527f9f23601f89`
for `local_files.py`. These short health/readiness results are not production
capacity measurements.

The before/after comparison preserved all 478 original containers, 257 volumes,
networks/images, protected files and 60 completed scanner states. Main rows,
schema/sequences/metadata, uploads, nine container definitions and deployment/WSL
fingerprints matched. All 23 new containers stopped without OOM and with restart
disabled; their six volumes were retained. Final inventory: 501 containers,
263 volumes, 65 stopped scanners; only the original nine containers running.

All 85 root regressions, Ruff and compilation passed. No implementation fix was
needed. Receipts and private integrity snapshots remain under `.venv`; existing
data, user work and WSL settings were not changed. Docker Desktop itself was not
restarted. This smoke does not exercise portable backup encryption/restore;
the separate native Windows backup regressions remain part of the root suite.

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

## Full scanner re-verification on 2026-10-17

The combined command passed on source revision `2e9de1c` with the cached images
documented above:

```powershell
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_telegram_ai.py --scanners
```

Docker Desktop was initially stopped. Native `docker desktop start --timeout 180`
exited 0 on Desktop 4.95.0 / Engine 29.8.2 without manual IPC repair. File hashes
were saved before startup; the read-only main database/container baseline was
captured after startup and before creating either fixture. All 35 retained smoke
scanners stayed stopped with `restart=no` after Desktop startup.

The controlled AI fixture passed real issuer/tenant/bot admission, PostgreSQL and
broker outages, consumed-notification recovery, lost-admission-receipt replay and
automatic restarts of all four permanent scanners. Exactly one generation,
usage, reply and canonical send remained; publication attempts were two. Tenant,
deactivation, conflict and duplicate denials passed; legacy AI tables stayed empty.

The separate legacy fixture passed upload/Celery/PostgreSQL-chunk verification,
JWT denials and exactly two events/deliveries/signed numeric-IP callbacks. Its API
restarted in the same container without Redis: live 200, ready 503, retained
event identity, HMAC/API-key 401 and shared PostgreSQL quota 429. Broker recovery
and the legacy scanner's automatic restart introduced no duplicate delivery.

Both credential-free receipts match the current driver/fixture source hashes.
All 23 new containers stopped without OOM; the five scanners exited 143 with
`restart=no`, while other processes exited 0. All 358 pre-existing container IDs,
images, start/finish times, restart counts/policies and running/OOM states matched
the pre-smoke inventory. All 224 existing volumes were retained; six new fixture
volumes were retained as well. Main rows/schema/sequences/metadata, nine container
definitions, upload contents/modes and configuration/WSL hashes were unchanged.
All six available main healthchecks were healthy. Forty-three root regressions,
Ruff and compilation passed. No application code change was needed.

One unfiltered read-only inventory query reported a missing rw-layer snapshot
for a pre-existing dead container in another project. Narrow inspection worked
and its runtime metadata matched the baseline; that unrelated storage issue was
not repaired or deleted. This did not fail either owned fixture. Raw operational
snapshots and local receipts remain private and are not published.

## Dead-container inventory diagnosis on 2026-10-18

The earlier warning reproduces with Docker CLI / Engine 29.8.2 and the containerd
overlayfs snapshotter. A pre-existing worker in another Compose project remains
`dead`; ordinary inspection succeeds and reports no attached mounts. This does
not establish that its writable layer has no data or that its project has no volumes.

`docker ps --all --format '{{json .}}'` implicitly requests container sizes:
the CLI's [JSON formatter](https://github.com/docker/cli/blob/v29.8.2/cli/command/formatter/reflect.go)
invokes `Size`, which [enables the size request unless explicitly disabled](https://github.com/docker/cli/blob/v29.8.2/cli/command/container/list.go).
The running Engine's [layer-size query](https://github.com/moby/moby/blob/8af9fe3/daemon/containerd/service.go)
returns the reported error when the snapshotter cannot find that container's
writable-layer usage. Why the historical snapshot became unavailable is unknown.

Use an explicit metadata-only query:

```powershell
docker ps --all --size=false --format '{{json .}}'
docker ps --all --filter status=dead --format '{{.ID}}|{{.Names}}|{{.Status}}'
```

Both commands exited 0; the first returned all 381 containers, including the dead
worker. Filtered JSON without the flag and explicit `--size` each exited 1 for
the same ID; filtered metadata and ordinary `docker inspect` exited 0. Ignore
the JSON `Size: 0B` placeholder: no size was measured. Existing fixture ownership
checks already use quiet IDs followed by inspection and need no code change.

This workaround restores metadata inventory, not the dead container or its
snapshot. No container, image, layer or volume was removed; Docker/WSL were not
restarted or reconfigured, and no Telegram/LLM was enabled. Raw inspection and
command receipts remain private.

Before/after comparison retained all 381 container identities, runtime states,
images, restart counts/policies and mounts, and all 230 volume names. Main database
rows/schema/sequences/metadata, uploads and protected configuration/WSL hashes
matched; nine main containers remained running and all six healthchecks healthy.
Forty-three root regressions, Ruff, compilation and `git diff --check` passed.

## Full scanner smoke with safe inventory on 2026-10-18

The combined `scripts/verify_telegram_ai.py --scanners` command passed on revision
`da72edc` with the cached images documented above. JSON inventory explicitly used
`--size=false` before, during and after the run: 381 containers before, 404 after.
The old dead worker was retained and did not interrupt any inventory query.
Unmeasured `Size` placeholders were not used as storage evidence.

The controlled AI fixture passed PostgreSQL/broker outages, consumed-notification
and lost-admission-receipt recovery, and automatic restarts of all four permanent
scanners. Exactly one generation, usage, reply and canonical send remained;
publication attempts were two. Duplicate/conflict/tenant/deactivation denials passed.
The separate legacy fixture passed upload/Celery/PostgreSQL checks, API restart
without Redis with live 200 / ready 503, retained event identity/quota/HMAC, and
exactly two signed numeric-IP callbacks without repeats after scanner restart.

Both receipts match the current driver/fixture source hashes. All 23 new
containers stopped without OOM: the five scanners exited 143 with `restart=no`,
the other 18 exited 0. All 40 previously completed scanners stayed stopped with
unchanged identities/start/finish times/restart counts/policies; all 45 retained
scanners now have `restart=no`.

All 381 pre-existing container definitions/runtime records, existing networks,
cached image IDs and 230 volume records matched the before-run baseline. Six new
fixture volumes were retained, bringing the total to 236. Main database
rows/schema/sequences/metadata, uploads and configuration/WSL hashes matched;
nine main containers remained running and all six healthchecks healthy.
Forty-three root regressions, Ruff and compilation passed. No application fix,
shared Docker/WSL restart or real Telegram/LLM activation was needed. Operational
snapshots and receipts remain private.

## Native Desktop restart with 45 completed scanners on 2026-10-18

With all 45 completed scanners stopped and `restart=no`, the explicitly requested
native command passed on Desktop 4.95.0 (242831), CLI / Engine 29.8.2:

```powershell
docker desktop restart --timeout 180
```

It exited 0 in 20.782 seconds and changed the Desktop session and all nine main
container start times. No manual IPC recovery, forced termination, volume cleanup,
WSL command or configuration edit was performed. Two post-restart inspections
194 seconds apart retained every scanner ID, last start/finish time, exit code
and restart count; all 45 remained stopped with `restart=no`.

All 404 container identities/images and 236 volume records were retained. All
395 previously stopped containers kept their process-state fingerprints. Main
definitions/mounts, database rows/schema/sequences/metadata, uploads,
`.env`/release/WSL hashes and Desktop preferences matched the before baseline.
All nine main processes were running without OOM and six healthchecks healthy;
HTTP `/health` on 28080, 8001, 8014 and 8080 returned 200. Both workers logged fresh
readiness without tracebacks; the main legacy scanner reported only `submitted=0`.
Main platform flags stayed disabled and provider credentials remained empty;
no real Telegram/LLM was enabled. Safe JSON inventory with `--size=false` returned
all 404 containers, including the unchanged old dead worker.

The strict configuration comparison initially detected `null` to `[]` changes
in three empty DNS fields of 46 recently created fixture containers. Reversing
only those fields reproduced all 46 original definition hashes; other inspected
configuration was unchanged. The private comparator now checks this exact case
and rejects injected custom DNS, changed restart policy or stopped start time.
See [the diagnostic](ERRORS.md#2026-10-18-native-docker-restart-changed-empty-dns-field-representation).
Existing network descriptors and image IDs matched; only the built-in bridge ID
and dynamic main network endpoint fields changed during restart.

Redis db1 retained all 17 logical values and absolute expiries. Db2/db3 each
retained the same three keys, types and expiries; one existing Celery binding set
in each gained one member and lost none. No Redis restore or key cleanup occurred.
Private before/after hashes and command receipts are retained locally. This checks
one native restart; Windows reboot, forced failure and sleep/resume are outside
this acceptance.

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
