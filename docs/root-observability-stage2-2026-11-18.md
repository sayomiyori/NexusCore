# Root observability Stage 2 acceptance — 2026-11-18

Status: **accepted** for the Stage 2 exit gate in
`specs/root-observability-integration.md` §8.3. One relay defect was found during
the run and fixed; the remaining duplicates are the documented Stage 3 gap, not a
Stage 2 regression.

## Environment

- PipeWatch `master` `ff44a10` (PR #2), EventPipe `main` `e450478`.
- Both profiles ran in project `nexuscore` with `--no-deps`, so the base stack was
  not recreated or stopped.
- Temporary subnet overrides (`10.255.254.0/24`, `10.255.253.0/24`) avoided the
  exhausted Docker address pools; they are not committed.
- A temporary env file supplied the EventPipe database password and the PipeWatch
  ClickHouse password; the repository `.env` was not modified and no secret was
  printed.
- Root `nexus-webhook-api` / `nexus-agent-api` were recreated from their own
  inspected env with `PLATFORM_BOTS_ENABLED=true` and
  `PLATFORM_READ_ENABLED=true`/`PLATFORM_TENANT_ENABLED=true`, and their service
  aliases (`webhook_service`, `agent_service`) were restored. Without the aliases
  AgentHub could not resolve the WebHook internal URL and returned 503.
- Fixture: synthetic AuthFortress owners/tenants, `telegram_bots` rows in
  `webhook_manager`, and `completed` `telegram_ai_jobs` rows in `agenthub`
  (64-character digest, provider/model/answer filled to satisfy the table
  checks). No provider was called.

## Evidence

| Gate | Result |
| --- | --- |
| `docker compose --profile observability-logs config --quiet` | exit 0 |
| `pipewatch`, `pipewatch_clickhouse`, `pipewatch_redis` | healthy |
| `GET /health`, `GET /ready` | `{"status":"ok"}`, `{"status":"ready"}` |
| `GET /metrics` | `404` |
| Redis `appendonly` / `appendfsync` / `maxmemory-policy` | `yes` / `always` / `noeviction` |
| ClickHouse `pipewatch.logs` TTL | `toIntervalDay(30)` |
| Relay sweep (tenant A) | `{"pending":0,"accepted":6,"unknown":0}` — three event types × two sinks |
| EventPipe sink | 3 rows, one per `ai.job.observed`, `auth.tenant.observed`, `webhook.bot.observed`, payload envelopes equal |
| PipeWatch sink | one row per trace, `metadata` equal to the envelope, `total=1` |
| Repeated sweep, same state | `{"pending":0,"accepted":6,"unknown":0}`; EventPipe still 3 rows, PipeWatch still `total=1` per trace |
| Tenant B token against tenant A scope | `agent` 404 `Scope not found`, `auth` 404, `webhook` 404 |
| Tenant B reading its own scope | EventPipe `200 rows=0`, PipeWatch `200 total=0` |
| Tenant A storage UUID read as tenant B | `404 event not found` for all three |
| EventPipe outage (ingest stopped) | exit 1, `{"pending":0,"accepted":3,"unknown":3}` |
| Repeat during outage | unchanged: `unknown=3`; no automatic resend |
| Reconciliation after recovery | exit 1, `{"confirmed":0,"unresolved":3,"duplicates":0,"conflicts":0,"errors":0}` — EventPipe never accepted those events |
| Outage run sinks | EventPipe 0 rows for the tenant, PipeWatch one accepted row per trace |
| Backlog (`APP_QUEUE_MAXSIZE=2`, `APP_BATCH_SIZE=1`, ClickHouse stopped) | `200`, `200`, `429`, `429` — no false `200` with a dropped record |
| Backlog drain after ClickHouse restart | both accepted records queryable, `total=2` |
| Alert cooldown (threshold 1, window 1 min, cooldown 5 min, ten matching logs) | exactly 1 event, `delivery_status=not_requested`, still 1 after three further evaluation cycles |
| LLM/Telegram calls | none: no provider or Telegram request in the service logs, telegram flags stayed `false` |
| Base stack | running, original volumes and rows untouched |

## Relay defect found and fixed

`metadata_envelope("auth", …)` used `datetime.now(UTC)` for `occurred_at` while the
event ID ignored poll time. Reconciliation compares whole envelopes, so a second
sweep produced the same `event_id` with a different `occurred_at` and reported a
permanent `conflict`. The envelope now uses the tenant `created_at`, which is both
deterministic and semantically correct; `tests/test_verify_observability.py`
asserts full envelope equality across two collections.

## Known non-gates

- Re-running the relay with a *different* state file re-delivers the same accepted
  envelopes, so PipeWatch ends up with a second row per trace. This is the
  at-least-once contract and the documented Stage 3 duplicate gap (§8.4 item 1);
  a repeated run with the same state adds nothing.
- `unknown` EventPipe deliveries are never resent automatically; reconciliation
  only reports them.
- The synthetic AuthFortress users/tenants, bot rows and AI job rows were created
  for this acceptance and remain in the local root databases.

## Reproducing the backpressure gate

`docker-compose.observability-test.yml` is the disposable override referenced in
§8.3. Run it in its own project so the root profile is untouched:

```powershell
docker compose -p pipewatch-bp -f docker-compose.yml -f docker-compose.observability-test.yml `
  --profile observability-logs up -d --no-deps pipewatch_clickhouse pipewatch_redis pipewatch
docker network connect nexuscore_nexus_net pipewatch-bp-pipewatch-1
docker stop pipewatch-bp-pipewatch_clickhouse-1
# POST three logs to 127.0.0.1:28085; the third must answer 429.
docker start pipewatch-bp-pipewatch_clickhouse-1
docker compose -p pipewatch-bp -f docker-compose.yml -f docker-compose.observability-test.yml down
```

## Cleanup

- Both observability profiles stopped; containers and their volumes retained except
  the disposable Kafka data volume, which had to be recreated because its stored
  cluster ID no longer matched a fresh ZooKeeper.
- The disposable backpressure project and its networks were removed.
- `nexus-webhook-api` / `nexus-agent-api` restored to the pre-acceptance containers
  (platform flags `false`); both healthy.
