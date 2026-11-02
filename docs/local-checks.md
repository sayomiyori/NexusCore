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

## Optional Windows coordination Hub checks

The coordination Hub is a Windows-only local pilot, so this section is optional
and leaves the cross-platform recipe above unchanged. It reuses the two existing
requirement files and adds no pin to `requirements-checks.txt`.

Host prerequisites are fixed and user-specific rather than generic: Git at
`C:/Program Files/Git/cmd/git.exe`, the private PowerShell path hardcoded in
`coordination_hub/persistent.py` (`_powershell`), currently
`C:/Users/flamx/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe`,
and Windows ACL support with restricted-owner directory creation. No sibling
checkout, live Hub database, Docker stack or real agent worktree is needed: the
tests create disposable Git repositories and temporary databases, and read no
production coordination data.

```powershell
py -3.12 -m venv .venv/hub-checks
.venv/hub-checks/Scripts/python.exe -m pip install -r requirements-checks.txt -r coordination_hub/requirements.txt
.venv/hub-checks/Scripts/python.exe -m pip check
.venv/hub-checks/Scripts/python.exe -m ruff check coordination_hub tests/coordination
.venv/hub-checks/Scripts/python.exe -m compileall -q coordination_hub tests/coordination
.venv/hub-checks/Scripts/python.exe -m unittest discover -s tests/coordination -p 'test_*.py' -v
```

Measured on 2026-11-02 with Python 3.12.10 and both requirement files installed:
`pip check` reports no broken requirements, the lint and compile steps are clean,
the root discovery command shown earlier in this document reports 164 tests, and
the separate Hub discovery command in this section reports 73 tests.

The optional Hub lint and compile commands here name both paths explicitly,
because `coordination_hub` is runtime code that the unchanged CI workflow neither
executes nor lints. The Hub suite also needs its own discovery because the root
pattern `test_verify*.py` does not match its file names. This is not wired into
`.github/workflows/local-checks.yml`, which keeps its current cross-platform
scope and runs only the root unit, lint and compilation checks; no Linux or CI
evidence is claimed for the Hub tests.

## Isolated Telegram edge check

With Docker already available and a locally cached Python image, run:

```powershell
.venv/checks/Scripts/python.exe scripts/verify_telegram_edge.py --python-image python:3.12-slim
```

This starts only a uniquely named synthetic receiver/nginx project, without
application `.env`, deployment storage or real provider traffic. Both fixture
networks use explicit private subnets; a Docker pool-overlap error permits up to
eight startup attempts, with successful owned cleanup required between attempts.
Other startup errors fail immediately. The driver removes its own containers
and networks on exit and does not prune volumes or foreign resources.

The concurrency check holds all 16 slots for client A, requires 503 for A and
202 for client B and a request without the proxy client header. This detects a
regression to a shared server bucket. It does not establish the trustworthiness
of client headers on a live network or verify a real Cloudflare tunnel.

`.github/workflows/local-checks.yml` runs the root unit, lint and compilation
checks on GitHub-hosted Ubuntu and Windows for relevant main pushes and pull
requests, and allows manual runs. It does not run the Docker edge driver.
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

The metrics, standalone/AI smoke and Telegram-edge CLIs use the same static
argument-error policy; rejected values and unknown options are withheld before
any HTTP/Docker/fixture action. Their valid arguments and help remain unchanged.
See [the verification CLI privacy contract](../specs/verification-cli-privacy.md).

The load probe streams raw response payloads without buffering or decompressing the
whole body. Each response must be at most 64 KiB, regardless of Content-Length;
oversized fixed-length or chunked responses fail without a success report.
Latency includes the entire accepted response. This bounds response payload,
not total process memory or a wall-clock deadline: the five-second HTTP timeout
limits inactivity, so a trickling peer can extend a run beyond its duration.
