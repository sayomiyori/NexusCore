# Local load probe reporting

The existing bounded loopback GET probe needs a latency acceptance check and
saved reports for repeatable local verification. Its URL allowlist,
duration/concurrency bounds, proxy/redirect restrictions and default JSON report
remain unchanged.

## Latency gate

`--max-p95-ms NUMBER` accepts a positive finite number. The CLI compares it to
the reported `p95_ms` (rounded to two decimal places). p95 selects the sorted
sample at one-based rank `ceil(0.95 * requests)`. For two samples, p95 is the
slower request. Equality passes. A higher p95 exits with code 1 and an explanatory
stderr message; stdout still contains the normal JSON report. An invalid limit
exits with code 2 before any HTTP request. Omitting the flag preserves existing
behavior. `verify()` keeps its existing signature and return value.

URL parsing, the loopback/path allowlist, ports 1..65535, expected statuses
200/401 and integer duration/concurrency bounds are checked before HTTP.
Whitespace/control characters are rejected before URL normalization.
Invalid probe inputs exit with code 2 and a static explanation, without echoing
the URL or a traceback. Optimized Python remains rejected before HTTP.

HTTP connection, timeout, protocol and unexpected-status failures exit with
code 1. Stderr identifies the failure class without exception details, URL,
response body or traceback. An unsuccessful probe emits no JSON success report
and creates no output file. This is distinct from a completed probe failing its
latency gate, which retains its JSON measurements.

After any worker failure, other workers stop at their next loop iteration.
Requests already in flight keep their existing 5-second HTTPX timeout; cancellation is
cooperative. Test this with two synchronized loopback clients: one returns 503,
the other returns 200, and a 30-second probe must fail within a 10-second budget
without stdout JSON or an output file.

```powershell
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_local_load.py http://127.0.0.1:55921/health --duration 5 --concurrency 1 --max-p95-ms 500
```

Use an explicitly isolated local listener. Auth probes can append audit records;
do not point them at the main deployment during feature verification.

## JSON report export

`--output PATH` writes the same JSON report as stdout to a new UTF-8 file, with
a trailing newline. The parent directory must exist. Existing files/directories
and missing parents are rejected before the probe, with exit code 2. Exclusive
creation also prevents overwriting a file created during the probe. Write errors
exit with code 2; a probe failure does not create a report. A failed latency gate
still saves its report before returning code 1. No URL, body, headers or credentials
are added to the report. Omitting the flag writes no file.

```powershell
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_local_load.py http://127.0.0.1:55921/health --duration 5 --concurrency 1 --max-p95-ms 500 --output .venv/local-load-report.json
```

Choose a new output filename for every run; directories are not created implicitly.
A write failure can leave an incomplete new file; exit code 2 marks that failure.

## Acceptance

- Cover below/equal/above threshold and zero, negative, NaN and infinite limits.
- Preserve all existing safety and default-report regression tests.
- Exercise actual CLI success/failure against a disposable loopback HTTP server.
- Compare saved reports to stdout for passing and failing latency gates.
- Reject occupied/unavailable output paths and preserve concurrently created files.
- Confirm probe/write failures and default invocation do not produce misleading success.
- No new dependency, Docker/WSL change, main data mutation or provider call.

## Verification commands

```powershell
../WebHook_Manager/.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_verify_local_load.py' -v
../WebHook_Manager/.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_verify*.py' -q
../WebHook_Manager/.venv/Scripts/python.exe -m ruff check scripts/verify_local_load.py tests/test_verify_local_load.py
../WebHook_Manager/.venv/Scripts/python.exe -m py_compile scripts/verify_local_load.py tests/test_verify_local_load.py
```
