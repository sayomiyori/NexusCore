# Verification tooling errors

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
