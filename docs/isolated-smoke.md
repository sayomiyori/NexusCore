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

Every exit stops only owned containers and retains volumes for inspection.
The credential-free result is `.venv/nexus-smoke-<uuid>/receipt.json`, including
source hashes, checks, process proof and cleanup status. Captured command/log
errors are withheld from the CLI to avoid exposing credentials. Local receipts
and operational integrity snapshots are ignored and are not published.

## Regression commands

On 2026-10-14, offline legacy admission and recovery passed with the updated
WebHook image: 202/200 while Redis was stopped, HMAC/API-key denials, shared 429
quota before/after broker recovery and two callbacks after scanner recovery.
The separate publishable-source runtime passed with its single new migration
head and one callback. Its full service suite passed 351 tests (85.86% coverage),
migration up/down/up/check, Ruff and strict Mypy. Twenty-eight root regressions
and fresh read-only adversarial/security review passed. Original root integrity
matched the before-task snapshot; all new test containers were stopped.

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
