# Bounded HTTP load in isolated smoke fixtures

The next capacity-roadmap increment is a repeatable local HTTP baseline, using
the existing fixture and load probe. Public deployment, sustained capacity,
business-operation throughput, Telegram/LLM activation and main data are excluded.
No new dependency, host port, WSL setting or external credential is needed.

## Contract

`verify_stack.py --load` and `verify_telegram_ai.py --load` opt in to a fixed
profile: five seconds, four concurrent clients, expected HTTP 200 and p95 at most
500 ms, sequentially for Auth `/health`, WebHook `/health/ready` and Agent `/health`.
`--scanners` remains composable. The AI driver forwards `--load` to its subsequent
standalone fixture; the two stacks never overlap.

Run the existing loopback-only `verify_local_load.py` inside each inspected owned
API container. Mount that script and its `local_files.py` dependency read-only,
from exact repository paths, at fixed `/verification` paths. Do not widen its
URL allowlist or add published ports. Validate fixture configuration/ownership,
exact container identity and running/no-OOM state before the probe.

Retain measurements for each completed role in the fixture receipt, even when a
latency gate fails. Any transport/status/gate/ownership failure makes the whole
fixture fail and still follows existing owned-only stop/restart-disable cleanup.
Record both load-source hashes; never persist URL, response bodies or credentials
in load measurements. Default smoke behavior has no load stage.

The clients share the API container's memory/CPU budget. This is a bounded local
health/readiness check, not an external-client benchmark or production SLO.

## Acceptance

- Cover flag/default/AI-forwarding behavior and successful receipt measurements.
- Refuse unowned/replaced/stopped/OOM roles before the first load command.
- Reject unsafe/writable/foreign probe mounts during configuration validation.
- Fail p95 above 500 ms; preserve measurements and cleanup failure semantics.
- Run root regressions, Ruff/compilation, fresh read-only/security review and
  real isolated `--scanners --load` acceptance with read-only before/after
  deployment, existing container/volume and completed-scanner integrity checks.
