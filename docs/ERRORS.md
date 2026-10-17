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
