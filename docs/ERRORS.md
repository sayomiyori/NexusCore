# Verification tooling errors

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
