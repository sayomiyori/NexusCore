# Legacy webhook delivery claim

Status: implementation under the user's project continuation request.

## Goal and scope

Prevent two Celery tasks from sending the same legacy delivery concurrently.
Reuse the existing PostgreSQL delivery status and synchronous worker session.
No schema, dependencies, HTTP payload or retry configuration changes.
Broker publication recovery, endpoint-wide concurrent counters, unknown external
outcomes, tenant integration and SSRF policy remain separate increments.

## Contract

- Lock the delivery row before inspecting its status and claiming it.
- Return existing success/exhausted outcomes; a delivering row returns delivering
  without HTTP or retry, even when task references differ.
- Pending/failed/retrying rows may transition to delivering. Commit the claim before
  HTTP; release the row lock at that commit, rather than holding it across HTTP.
- Persist success/failure using existing behavior. Confirmed failure retains the
  existing bounded Celery retry path.
- A worker lost after its claim leaves delivering visible. Do not automatically
  resend it: the remote effect may already have happened. Operator reconciliation
  remains required; this increment does not provide exactly-once delivery.

## Acceptance

Real isolated PostgreSQL and Redis are required. A regression must show that a
second task during a blocked first HTTP call performs no second HTTP request.
Independent connections racing before claim must serialize and produce one send.
Delivering replay with forged references must preserve the active claim. Existing
success/retry/circuit tests, full suite, Ruff and strict Mypy remain green.
Fresh read-only adversarial/security review must approve before commit/push.

## Files

WebHook Manager: `src/infrastructure/queue/tasks/deliver_webhook.py`,
`tests/integration/test_worker_delivery.py`, README and `docs/ERRORS.md`.
NexusCore: current verification report and project map.
