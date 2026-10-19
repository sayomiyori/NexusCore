# Run root verification checks independently

Use Python 3.12 and a disposable virtualenv. The root tests need no sibling
checkout, Docker, application `.env`, database or real Telegram/LLM account.
The pinned development dependencies cover the existing HTTP/crypto/database
boundary doubles and Ruff; they do not install the sibling applications.

On Windows PowerShell:

```powershell
python -m venv .venv/checks
.venv/checks/Scripts/python.exe -m pip install -r requirements-checks.txt
.venv/checks/Scripts/python.exe -m pip check
.venv/checks/Scripts/python.exe -m ruff check scripts tests
.venv/checks/Scripts/python.exe -m compileall -q scripts tests
.venv/checks/Scripts/python.exe -m unittest discover -s tests -p 'test_verify*.py' -v
```

On Linux/macOS use `.venv/checks/bin/python` instead of the Windows executable.
Dependency installation requires package-index access. The tests themselves use
mocked Docker/HTTP boundaries and disposable loopback listeners. They do not
start a Docker stack or read the main deployment configuration.

`.github/workflows/local-checks.yml` runs these checks on GitHub-hosted Ubuntu
and Windows for relevant main pushes and pull requests, and allows manual runs.
Workflow permissions are read-only; checkout credentials are not persisted.

These checks cover verification-tool regressions. For actual service/scanner
acceptance, follow [the isolated smoke guide](isolated-smoke.md); a green root
test suite is not evidence of live Telegram/LLM, Docker or production readiness.

The same environment runs [portable backup artifact encryption](portable-backups.md).
Its tests use generated keys and disposable files, never deployment data.

The load CLI returns static diagnostics and exit 2 for all argument errors,
including malformed numeric values and unknown options. It never echoes rejected
arguments. Runtime HTTP failures retain static diagnostics and exit 1; `--help`
remains available. See [the local probe safety contract](../specs/local-load-safety.md).

The probe streams raw response payloads without buffering or decompressing the
whole body. Each response must be at most 64 KiB, regardless of Content-Length;
oversized fixed-length or chunked responses fail without a success report.
Latency includes the entire accepted response. This bounds response payload,
not total process memory or a wall-clock deadline: the five-second HTTP timeout
limits inactivity, so a trickling peer can extend a run beyond its duration.
