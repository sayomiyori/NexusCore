# Local load probe reporting

The existing bounded loopback GET probe needs a latency acceptance check for
repeatable local verification. Its URL allowlist, duration/concurrency bounds,
proxy/redirect restrictions and default JSON report remain unchanged.

## Latency gate

`--max-p95-ms NUMBER` accepts a positive finite number. The CLI compares it to
the reported `p95_ms` (rounded to two decimal places, using the existing sample
selection). Equality passes. A higher p95 exits with code 1 and an explanatory
stderr message; stdout still contains the normal JSON report. An invalid limit
exits with code 2 before any HTTP request. Omitting the flag preserves existing
behavior. `verify()` keeps its existing signature and return value.

```powershell
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_local_load.py http://127.0.0.1:55921/health --duration 5 --concurrency 1 --max-p95-ms 500
```

Use an explicitly isolated local listener. Auth probes can append audit records;
do not point them at the main deployment during feature verification.

## Acceptance

- Cover below/equal/above threshold and zero, negative, NaN and infinite limits.
- Preserve all existing safety and default-report regression tests.
- Exercise actual CLI success/failure against a disposable loopback HTTP server.
- No new dependency, Docker/WSL change, main data mutation or provider call.
