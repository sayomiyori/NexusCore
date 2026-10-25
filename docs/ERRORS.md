# Verification tooling errors

## 2026-10-25: Dashboard bot names counted UTF-16 units instead of characters

- Symptom: the unshipped Bots BFF rejected a valid backend name with 65–128
  astral Unicode characters and made the entire page unavailable.
- Cause: the existing generic `text(value, 128)` guard uses JavaScript length
  (UTF-16 units); Python validation/PostgreSQL VARCHAR(128) use code points.
- Fix: keep a bounded nonempty string guard (at most 256 UTF-16 units), then
  enforce at most 128 Unicode code points locally for bot names. Other transport,
  identifier and credential text bounds retain their existing semantics.
- Detection: `bot names use the backend Unicode code point limit` calls the real
  dashboard GET handler with HTTP source responses; 65/128 emoji return 200,
  129 return 502. Independent review reproduced the original failure and fix.

## 2026-10-23: Isolated SeaweedFS exhausted its single internal volume slot

- Symptom: the first private dashboard fixture's EventPipe transform exhausted
  bounded S3 retries and exited 1 with `transform infrastructure unavailable`.
  This attempt was retained as failed, not accepted as dashboard evidence.
- Cause: the reused fixture specified `-volume.max=1`. SeaweedFS allocated its
  only slot to the default collection; the separate `raw-events`
  collection then reported `No writable volumes and no free volumes left`.
  No OOM, shared deployment mutation or application validation failure was found.
- Fixture correction: use four internal SeaweedFS slots in a fresh UUID project
  and prove bucket create/write/read through the existing S3 client before
  starting transform. These are internal SeaweedFS slots inside one new Docker
  volume, not changes to any existing Docker volume. No cleanup is required.
- Detection: the original failed receipt/logs remain in the ignored private
  fixture directory. Final acceptance requires the explicit S3 readiness probe,
  three stored observation types and clean transform shutdown.

## 2026-10-23: Overview could present mismatched receiver types as empty

- Symptom: an unshipped dashboard draft treated a known outer event type with an
  unknown inner type as a successful empty receiver response.
- Cause: outer/inner type equality was checked only after the inner observation
  parser returned a supported event. Unknown inner types skipped that guard.
- Fix: compare the outer marker and inner type unconditionally before excluding
  unsupported types. A mismatch makes that receiver unavailable; the independent
  receiver can still provide its safe observations.
- Detection: `known outer markers cannot hide invalid inner types as successful
  empty reads` exercises both EventPipe and PipeWatch. Independent review's
  original HTTP reproduction now returns both sources unavailable.

## 2026-10-23: Reconciliation could miss an ID claimed under another outer type

- Symptom: the first unshipped reconciliation draft filtered EventPipe summaries
  by expected event type. A second record with a different outer type but the
  same payload/metadata relay ID was skipped, falsely reporting confirmation.
- Cause: a summary type filter hid records needed to detect identity conflicts;
  full payload and relay metadata are available only on the detail endpoint.
- Fix: inspect every listed `source=nexuscore` record within the fixed bounded
  scan, then match both identity claims and full content. A conflicting candidate
  takes precedence over otherwise matching copies. No state update or resend.
- Detection: `test_foreign_outer_event_type_cannot_hide_a_claimed_relay_identity`
  adds a differently typed conflicting copy with another storage UUID and
  requires one EventPipe conflict while PipeWatch still confirms its copy.

## 2026-10-22: Cached EventPipe dual CLI did not finish on HTTP shutdown

- Symptom: the new isolated observability fixture delivered and queried events,
  but its cached EventPipe ingest container required a forced stop (exit 137,
  OOM false). This attempt was retained as failed, not accepted.
- Cause: the image's module CLI awaited both Uvicorn and gRPC termination;
  HTTP shutdown left the gRPC wait alive before its `finally` cleanup.
- Integration correction: launch the existing ASGI application with
  `python -m uvicorn ingest_service.app.main:app --host 0.0.0.0 --port 8000`.
  Its existing lifespan owns Kafka/gRPC startup and shutdown. No dirty sibling
  source, image or existing deployment was modified.
- Detection: the final new UUID fixture stopped/restarted ingest during the
  partial-failure probe and stopped all services afterwards. Ingest and all
  Python applications exited 0 without OOM; stock Kafka/ZooKeeper exited 143
  under explicit SIGTERM. The standalone default CLI itself remains unchanged.

## 2026-10-21: Private inventory exceeded the Windows process argument limit

- Symptom: after a successful full scanner smoke, the private preservation
  collector failed before `docker inspect` launched: `WinError 206` at 524 full
  container IDs. The 501-container baseline had succeeded.
- Cause: the collector placed every 64-character ID in one process command line,
  exceeding the Windows process argument limit. Docker and the resources were
  healthy; no cleanup or runtime repair was needed.
- Fix: copy the historical collector definitions into the current private helper
  and inspect containers, volumes and networks in batches of at most 100 names.
  Concatenate parsed JSON records in order; retain all original equality checks,
  captured diagnostics and `docker ps --all --size=false`. Historical helpers,
  resources and snapshots remain unchanged.
- Detection: assert-based checks cover 0/1/100/101/524/526 IDs, exact order/count
  and the batch bound. Actual 524-container smoke and 526-container restore
  inventories passed, preserving all original resource records and protected
  hashes. No committed product code or deployment configuration changed.

## 2026-10-21: Remaining verification CLIs echoed rejected arguments

- Symptom: an invalid metrics role or unknown smoke/edge option appeared verbatim
  in stderr, despite safe diagnostics for later HTTP/Docker failures.
- Cause: these four entrypoints still used the default argparse error formatter;
  the load and backup tools already redacted syntax errors.
- Fix: apply the existing static parser-error pattern, with the AI driver reusing
  its existing smoke-module dependency. Valid arguments and runtime paths are unchanged.
- Detection: twelve direct invalid-argument cases prove no HTTP/Docker/temp-dir
  boundary is reached; real subprocess syntax/help checks withhold private values.

## 2026-10-19: Restart comparison rejected mixed empty DNS representations

- Symptom: after a successful native restart, the resource comparator rejected
  five stopped container definitions while all scanner process states matched.
- Cause: the previous representation proof assumed all three DNS fields were
  `null`. These five had `Dns=null` with `DnsOptions=[]` and `DnsSearch=[]`.
- Fix: only when all three observed fields are empty lists, test at most eight
  null/list combinations and require an exact match to the original complete
  Config/HostConfig/mount hash. No other field or running definition is normalized.
- Detection: all 97 changed hashes were reproduced exactly (92 all-null, five
  mixed). Negative checks reject custom DNS, policy, stopped start time/restart
  count, missing volume, Redis absolute-expiry and WSL hash drift. Initial failed
  comparison artifacts were retained; no container or host settings were changed.

## 2026-10-19: Windows backup input opens followed a substituted file link

- Symptom: replacing a synthetic dump with a symlink after path validation
  redirected `read_file()` to another synthetic file.
- Cause: Windows CRT `os.open()` followed final-component reparse points;
  `O_NOFOLLOW` was unavailable and the preliminary path check could race.
- Fix: native existing-file opens use `OPEN_REPARSE_POINT`; reject non-disk
  handles and reparse attributes before reading. Share only readers, retain
  handle cleanup and POSIX nonblocking/no-follow plus regular-file validation.
- Detection: dump/key links inserted at the open boundary fail without an
  artifact; device inputs and existing exclusive-output regressions also pass.

## 2026-10-19: Load requests buffered and decompressed unlimited response bodies

- Symptom: a synthetic 1 MiB health response was fully loaded and accepted.
- Cause: `client.get()` eagerly read/decompressed each body despite the tool
  needing only status and response latency.
- Fix: use the HTTPX streaming context and count raw payload bytes, with a
  64 KiB per-response limit and no body retention/decompression. Existing worker
  failure cancellation and static CLI failure handling remain in force.
- Detection: empty/exact-limit/compressed bodies, oversized and interrupted
  streams, status-before-body checks and real fixed/chunked loopback CLI failures.

## 2026-10-19: Load CLI syntax errors disclosed supplied argument values

- Symptom: a nonnumeric `--duration` value appeared verbatim in stderr.
- Cause: the default argparse formatter included rejected values and unknown
  options before the tool's safe validation/runtime handlers ran.
- Fix: use static parser diagnostics for every argument error, preserving exit 2
  and normal help. Runtime transport failures keep their safe exit-1 contract.
- Detection: malformed numeric/status values, unknown options, extra positional
  arguments and missing values fail before HTTP without input disclosure.

## 2026-10-17: Short-sample p95 could pass a failed latency gate

- Symptom: two requests taking 1 ms and 100 ms passed `--max-p95-ms 50`.
- Cause: rounding `(requests - 1) * 0.95` down selected the faster sample.
- Fix: use the nearest-rank definition, `ceil(0.95 * requests) - 1`.
- Detection: `test_short_sample_p95_does_not_hide_a_slow_request_from_gate`
  exercises the real probe and CLI gate with controlled HTTP and clock boundaries.

## 2026-10-17: Invalid probe inputs produced tracebacks and inconsistent errors

- Symptom: malformed/nonlocal hosts echoed input in a traceback; invalid ports
  could reach the HTTP client instead of failing during validation.
- Cause: assertion guards missed parsed ports and `urlsplit` normalized control characters.
- Fix: explicit static validation errors, checked ports, control/whitespace rejection
  before URL parsing and CLI usage exit code 2.
- Detection: `test_invalid_probe_inputs_are_usage_errors_without_input_disclosure`
  verifies malformed URLs, unsafe destinations and bounds without opening a client.

## 2026-10-17: HTTP probe failures leaked exception details in tracebacks

- Symptom: connection, timeout, protocol and unexpected-status failures bypassed
  the CLI failure contract and printed exception details.
- Cause: worker failures propagated through the executor without CLI handling.
- Fix: report only the failure class on stderr and exit 1, without a success artifact.
- Detection: transport/status boundary regressions and an actual CLI connection
  refusal against an exclusively bound, non-listening loopback socket.

## 2026-10-17: Failed concurrent probe continued sending requests

- Symptom: after one client received 503, another issued thousands of requests
  until the configured duration ended. A 30-second run exceeded a 10-second test budget.
- Cause: executor shutdown waited for independent worker loops to reach the deadline.
- Fix: a shared event makes all workers stop scheduling requests after a worker failure.
  Already in-flight requests retain their existing HTTP timeout.
- Detection: `test_one_http_failure_stops_the_other_worker_before_duration`
  coordinates two real loopback clients and asserts early failure without a report.

## 2026-10-18: JSON Docker inventory requested an unavailable dead-container size

- Symptom: `docker ps --all --format '{{json .}}'` failed with
  `rw layer snapshot not found for container ...` for an old worker in another project.
- Cause: Docker CLI 29.8.2 expands JSON through formatter methods, including `Size`,
  and implicitly requests sizes. Engine 29.8.2 then receives `NotFound` from the
  containerd snapshotter's writable-layer usage query. Metadata inspection succeeds;
  the historical cause of the missing snapshot is unknown.
- Workaround: pass `--size=false` explicitly for metadata inventory. Its `Size: 0B`
  is an unmeasured placeholder, not evidence that the container contains no data.
  The container remains `dead`; no layer recovery or deletion was performed.
- Detection: filtered JSON and explicit `--size` fail for that ID; filtered JSON
  with `--size=false`, plain metadata and `docker inspect` pass. The all-container
  metadata query returns all 381 retained containers without a daemon error.
  See [the command and preservation evidence](isolated-smoke.md#dead-container-inventory-diagnosis-on-2026-10-18).

## 2026-10-18: Native Docker restart changed empty DNS field representation

- Symptom: a strict definition fingerprint comparison failed for 46 recently
  created, stopped fixture containers after a successful native Desktop restart.
- Cause: inspection changed `HostConfig.Dns`, `DnsOptions` and `DnsSearch` from
  `null` to `[]`. Reversing only those three fields reconstructed each original
  full Config/HostConfig/mounts hash; process timestamps and restart counts matched.
- Fix: the private acceptance comparator first checks the raw hash. On mismatch,
  it accepts only three actual empty DNS lists whose reversal reproduces the exact
  before hash. All other configuration and stopped-process checks remain strict.
  Docker settings, containers and WSL are not modified by this comparison.
- Detection: the real before/after comparison passes; injected custom DNS,
  changed restart policy and changed stopped-container start time each fail.
  See [the 45-scanner restart acceptance](isolated-smoke.md#native-desktop-restart-with-45-completed-scanners-on-2026-10-18).

## 2026-10-19: Windows exclusive creation followed a dangling symbolic link

- Symptom: the first portable-backup implementation used CRT `O_EXCL`, which
  followed an existing dangling file link and created its absent target on Windows.
- Cause: the CRT file-open semantics did not provide the required final-component
  reparse-point protection, despite exclusive creation flags.
- Fix: Windows output creation uses native `CreateFileW` with `CREATE_NEW` and
  `FILE_FLAG_OPEN_REPARSE_POINT`. POSIX retains `O_EXCL` and `O_NOFOLLOW`.
- Detection: real CLI key generation/decryption into a dangling link both fail;
  a link inserted immediately before the native open also leaves its target absent.
  Invalid CLI syntax additionally uses static diagnostics to withhold arguments.

## 2026-10-19: Local load report followed a dangling output link on Windows

- Symptom: a symbolic link inserted during the HTTP probe redirected `--output`
  to an absent target; the CLI returned success after writing there. A pre-existing
  dangling link also passed the `exists()` preflight check.
- Cause: `Path.open("x")` used Windows CRT exclusive-creation semantics, which
  followed the link rather than rejecting its final component.
- Fix: reject links before HTTP and share the portable-backup tool's native
  exclusive creator in `scripts/local_files.py`. The helper uses only the standard
  library; probe report format and exit codes stay unchanged.
- Detection: before/after regressions cover a pre-existing dangling link and
  a link inserted during the probe, with absent and occupied targets. The target
  remains absent/unchanged, with usage exit 2; a pre-existing link sends no HTTP.
- Additional boundary: native `CREATE_NEW` could open Windows `NUL` as a character
  device and silently discard a backup key/report. The shared creator checks
  `GetFileType` before writing, closes non-disk handles and fails. The device
  regression checks both native creation and the actual backup CLI.

## 2026-10-19: Smoke receipt accepted a worker killed during parallel teardown

- Symptom: the full scanner/load smoke returned a successful receipt while one
  stopped AI worker had exit 137 and `OOMKilled=false`.
- Cause: final proof checked only stopped state and scanner policy. Teardown
  stopped applications and dependencies in parallel: Redis received SIGTERM at
  08:53:54.116 UTC and exited before the worker logged warm shutdown at
  08:53:54.166; Docker killed the worker after the 10-second grace period. The
  exact internal Celery shutdown wait was not established from those logs.
- Fix: stop running owned APIs/workers/scanners first with a 30-second grace
  period, keeping database/broker/callback alive. Always stop infrastructure
  afterward, including on error. Reject final OOM and unexpected exit codes;
  scanners retain their permitted SIGTERM exit 143.
- Detection: Docker-boundary tests enforce the order/fallback and reject 137,
  exit 1 and OOM despite stopped state. Existing scanner policy tests remain.
  A targeted owned-fixture rehearsal restarted only its Redis and affected
  worker: Celery ping passed, the worker exited 0 before Redis exited 0, all
  14 containers stopped, and the four completed scanners never restarted.
