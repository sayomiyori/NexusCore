# Current module verification — 2026-10-09

Scope: inspect and test existing independent services, repair reproduced defects,
measure affected paths, independently review changes and refresh documentation.
This is a local checkpoint, not a claim of complete production readiness.

## Results

| Service | Complete suite | Other checks |
| --- | --- | --- |
| AuthFortress | 192 passed, 25.94 s | Ruff; Mypy 39 files; Alembic no drift; real HTTP auth/tenant/RBAC/refresh/2FA races |
| WebHook Manager | 329 passed, 32.17 s | 85.24% coverage; Ruff; strict Mypy 118 files |
| AgentHub | 250 passed, 18.91 s | Ruff; CI Mypy scope 26 files; real pgvector/Redis integration |
| EventPipe | 27 passed, 13.51 s | Real Kafka/PostgreSQL/S3; full Ruff; SeaweedFS CI passed |
| PipeWatch | 25 passed, 2.74 s | Real ClickHouse/Redis; Ruff; source HTTP/WebSocket/CLI smoke |

Latest verified total: 823 tests. WebHook was rerun in the delivery claim
continuation below; EventPipe was rerun for the SeaweedFS CI correction.
The other three results retain the earlier checkpoint.
Timings are individual local runs, not load/capacity promises.
There are upstream deprecation warnings in AuthFortress, WebHook Manager,
AgentHub and PipeWatch. No test was skipped in the final EventPipe suite.

## Post-push GitHub Actions

- AuthFortress `9babd80`: CI run `37849265727` passed, including Docker build.
- WebHook Manager initial `48919e1`: CI `37849270738` and image publication
  `37849270749` passed. Continuation `da56722`: CI `37889515010` and publication
  `37889515020` also passed. This CD workflow does not deploy a VPS.
  Delivery claim follow-up `f4539ce`: CI `37964091828` and image publication
  `37964092052` passed, including security/lint/type/test gates and Docker build.
- AgentHub `ba930c5`: CI `37849276206` passed, including Docker build.
- EventPipe `cef1fd8`: CI `37849281566` failed before checkout/tests because its
  stale `minio/minio:latest` service cannot be pulled. An attempted replacement
  with the existing test Compose was blocked by automatic approval review
  (`blocked by policy`). The user subsequently applied the reviewed workflow.
  Follow-up `79ab8dd`: CI `37894123954` passed, including all 27 tests (8.47 s),
  zero-skip enforcement, three Docker builds and unconditional cleanup.
  Fresh read-only adversarial review and the scoped security pass approved.
- PipeWatch `8e1ebc2`: CI `37849286678` failed Python import collection. The
  follow-up `c9f965c` uses `python -m pytest`, the existing ClickHouse/Redis test
  Compose and a zero-skips assertion. Independent local review: 25 passed,
  zero skips; GitHub run `37849713020` passed, including Docker build and cleanup.

Checks used `gh run view <run-id> --repo sayomiyori/<repository> --json status,conclusion`
and `--log-failed`. Initial local verification preceded these remote outcomes.

Fresh read-only adversarial reviews approved AuthFortress, EventPipe/PipeWatch
and AgentHub/WebHook fixes. Review reproduced and required corrections for a
late Celery timeout after success, huge cache timestamps, malformed sources and
invalid UTF-8/NUL. The corrected regressions and independent reruns passed.

## Continuation: Redis circuit breaker

After the user requested continuation, the EventPipe workflow correction was
attempted again and rejected with `blocked by policy`. The workflow was not
changed and no alternate mechanism was used. Work continued on the independent
legacy WebHook circuit-breaker boundary.

Commit `da56722` bounds Redis socket/connect waits to 0.5 seconds, disables
transport retries and closes the per-task Redis client on every exit. Redis
read/INCR/EXPIRE errors no longer prevent the delivery outcome from being saved.
The PostgreSQL endpoint failure count still enforces the threshold; a smaller
Redis count cannot schedule another retry after the DB threshold is reached.
New logs carry UUIDs and static operation labels, not exceptions or credentials.

Five regressions failed before the fix; a sixth case checks DB count=10 with zero
HTTP calls. Final full suite: 326 passed. Independent review: 11 worker tests,
Ruff, Mypy and security pass approved. A mutation removing max(DB, Redis) failed
the threshold regression. A real local TCP server that accepted but never
answered a Redis request timed out after 0.519 seconds, with one connection.
This is a socket-wait probe, not a total task deadline or throughput benchmark.

Verification used a fresh tmpfs PostgreSQL `webhook_circuit_test` on port 59629
and an isolated Redis on 59630. `TEST_DATABASE_URL` and `TEST_REDIS_URL` selected
only those resources. Commands from WebHook Manager:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m pytest tests/integration/test_worker_delivery.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/ --cov=src --cov-report=term --cov-fail-under=80
.venv/Scripts/python.exe -m ruff check src/ tests/ scripts/ alembic/
.venv/Scripts/python.exe -m mypy src/ --strict
docker build -f .venv/module-audit.Dockerfile -t webhook-circuit-resilience:20261009 .
```

The controlled Telegram/AI chain passed with that image and the existing
AuthFortress/AgentHub images. No live Telegram/provider calls were made. Broker
publication loss, concurrent claims and ambiguous HTTP sends are still separate
recovery work; this change does not claim exactly-once delivery.

The local WebHook API/worker were updated through the retained host-local Compose
overrides. `scripts/verify_stack.py` passed after recreation; Celery inspect ping
returned one pong. A ten-minute log scan counted zero tracebacks/ERROR markers.
The two owned `nexus-circuit-audit-*` containers were stopped and removed by
their `--rm` policy; existing runtime volumes were preserved.

## Changes

- AuthFortress: resolve concurrent same-email registration as a conflict after
  rollback; move the complete synchronous audit session lifecycle off the event
  loop. Existing auth contracts and database schema remain intact.
- WebHook Manager: preserve committed success after late Redis/time-limit
  failure, honor configured HTTP timeout, avoid credential-bearing URL/error
  logs, forward history cursor/limit and traverse all subscription pages.
- AgentHub: Redis failures no longer break optional RAG cache access; bounded
  socket/connect waits, no transport retries, original entry age, vector/payload
  validation, metadata filtering before vector math. No new dependencies.
- PipeWatch: complete in-flight storage before graceful shutdown draining;
  confirmed inserts are not repeated when Redis publication is cancelled.
  Run blocking ClickHouse query handlers in FastAPI's existing threadpool.
- EventPipe: close partially started Kafka producers before retry, narrow retry
  exceptions, correct the main SeaweedFS health command and remaining Ruff
  findings. README now describes SeaweedFS rather than an absent MinIO console.
- NexusCore: configurable standalone LLM provider/model in both processes;
  optional `--auth-image` selects the actual image in controlled-chain acceptance.

Each service's `docs/ERRORS.md` records its regressions. Independent repositories
remain independent; user-owned Compose/image changes were not included.

## Commands and test infrastructure

Commands below run from the named repository. Each test process used its local
`.venv/Scripts/python.exe`. Integration credentials were synthetic, not copied
from application `.env`. Existing runtime databases were not used for pytest.

AuthFortress used fresh `authfortress_final_test` on PostgreSQL port 58432 and
Redis port 58379, DB 15. The HTTP probes used a separate synthetic database.

```powershell
.venv/Scripts/python.exe -m pytest -q --tb=short --durations=5
.venv/Scripts/python.exe -m pytest -q tests/test_concurrency_regressions.py --tb=short
.venv/Scripts/python.exe -m alembic check
.venv/Scripts/python.exe -m ruff check app tests scripts
.venv/Scripts/python.exe -m mypy app
.venv/Scripts/python.exe scripts/verify_auth.py --base-url http://127.0.0.1:58080
.venv/Scripts/python.exe -m scripts.verify_refresh_concurrency --base-url http://127.0.0.1:58080
```

The existing concurrency utilities still embed isolated test defaults; the
reviewer's additional races supplied this run's test configuration in an ignored
helper. Those utilities are not a portable production operator interface.

WebHook Manager used `TEST_DATABASE_URL` / `DATABASE_URL` targeting the isolated
`webhook_audit_test` on port 59629 and `TEST_REDIS_URL` on port 59630, DB 0.

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m pytest tests/ --cov=src --cov-report=term --cov-fail-under=80
.venv/Scripts/python.exe -m ruff check src/ tests/ scripts/ alembic/
.venv/Scripts/python.exe -m mypy src/ --strict
```

AgentHub used `DATABASE_URL`, `AGENTHUB_TEST_DATABASE_URL` and
`AGENTHUB_PLATFORM_TEST_DATABASE_URL` targeting isolated
`nexus_agent_ai_audit_test` on port 59629; `REDIS_URL` / `AGENTHUB_TEST_REDIS_URL`
targeted port 59630, DBs 1 and 15 respectively.

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy app/models/llm_usage.py app/services/usage_tracker.py app/metrics.py app/cache/semantic_cache.py app/platform app/api/internal app/api/v1/platform_reads.py app/db/platform.py app/models/telegram_job.py app/models/telegram_reply.py app/models/telegram_usage.py app/workers/telegram_worker.py app/workers/telegram_reply_worker.py scripts/recover_telegram_jobs.py scripts/recover_telegram_replies.py
```

EventPipe used `EVENTPIPE_KAFKA_BOOTSTRAP_SERVERS=localhost:59092`,
`TRANSFORM_INTEGRATION=1`, `TRANSFORM_KAFKA_BOOTSTRAP_SERVERS=localhost:59092`,
PostgreSQL port 55435/database `eventpipe_test`, S3 port 39000. PipeWatch used
ClickHouse port 58123/database `pipewatch_test`, Redis port 56383. Test credentials
followed their existing `docker-compose.test.yml` profiles.

```powershell
# EventPipe
.venv/Scripts/python.exe -m pytest -q --tb=short
.venv/Scripts/python.exe -m ruff check ingest_service transform_service query_service scripts --output-format concise
docker compose config --quiet
docker compose -f docker-compose.test.yml config --quiet
# Actual SeaweedFS image command: exit 0
docker exec nexus-observability-audit-s3-20261009 wget -q -O /dev/null http://127.0.0.1:9333/cluster/status
# PipeWatch
.venv/Scripts/python.exe -m pytest -q --tb=short
.venv/Scripts/python.exe -m ruff check app cli tests scripts
.venv/Scripts/python.exe scripts/verify_http.py
```

PipeWatch HTTP smoke targeted source uvicorn on port 38084, despite the utility's
historical wording `built`. The additional responsiveness probe used real
ClickHouse `SELECT sleep(0.3)` and shutdown probe used 100 unique records.

## Image and integration acceptance

Three application images copied changed application source onto the previously
verified local runtime images, retaining installed dependencies. This was not a
fresh dependency-resolution build. Ignored `.venv/module-audit.Dockerfile` files
contain the exact base tags and one `COPY app` / `COPY src` instruction.

| Image | Local image digest |
| --- | --- |
| `authfortress-resilience:20261009` | `sha256:6eed5d0700104497e08243ab39cad6c16b1eda020dabd056444f790b7269885d` |
| `agenthub-resilience:20261009` | `sha256:78d7ea5648b50f5aec7facfc1223be0391bec81166babf25db38005f23079cf6` |
| `webhook-circuit-resilience:20261009` | `sha256:549e869043f7ec813ab3f07b30e19867f327bc89107e511dd78197195161b7d4` |

```powershell
# In each corresponding service repository
docker build -f .venv/module-audit.Dockerfile -t <image-above> .
# From NexusCore, TEST_DATABASE_URL points to the isolated PostgreSQL above
../AgentHub/.venv/Scripts/python.exe scripts/verify_telegram_ai.py --webhook-image webhook-circuit-resilience:20261009 --agent-image agenthub-resilience:20261009 --auth-image authfortress-resilience:20261009
../AgentHub/.venv/Scripts/python.exe scripts/verify_telegram_edge.py --python-image agenthub-resilience:20261009
docker compose -f docker-compose.yml -f .venv/root-adoption.compose.yml -f .venv/root-auth-update.compose.yml config --quiet
docker compose -f docker-compose.yml -f .venv/root-adoption.compose.yml -f .venv/root-auth-update.compose.yml up -d --no-deps --no-build --wait --wait-timeout 120 auth_service webhook_service webhook_worker agent_service agent_worker
../AgentHub/.venv/Scripts/python.exe scripts/verify_stack.py
```

All passed. The controlled chain checked real issuer JWT, broker-outage intake,
replayed admission, controlled generation, one result/usage, signed publication,
canonical controlled send, duplicates/conflicts/auth/deactivation and legacy
isolation. The edge checked routes, methods, size/concurrency/idle limits,
header isolation, safe logs, no hidden forwarding/retries and upstream outage.

Local root APIs and workers were updated to those image digests; existing
databases/volumes were preserved. Platform/AI live flags remain disabled. Root
smoke creates and retains uniquely named demo records. No actual Telegram
messages, webhook changes or external LLM calls were performed in this run.

## Performance measurements

| Controlled scenario | Before | After |
| --- | --- | --- |
| Auth audit: 20 ms timer during 300 ms PostgreSQL lock | 302.6 ms | 26.8 ms |
| Auth `/api/v1/auth/me` rejection, 100 requests / concurrency 8 | 114.3 requests/s, p95 101.4 ms | 191.9 requests/s, p95 59.7 ms |
| PipeWatch timer during 300 ms ClickHouse query | 320 ms | 24 ms |
| Semantic cache lookup, median / p95 | 28.42 / 35.00 ms | 8.96 / 10.69 ms |

Cache comparison executed old HEAD source and changed source in the same Python
process: 60 lookups each, 64 records with 1536-dimensional vectors, only the last
record's provider matched, Redis replaced by a fixed in-memory response. Both
paths asserted the same answer. JSON decode was included, Redis/network/LLM
latency excluded. These probes show the specific improvement, not production
throughput, RAG quality or long-running capacity.

Cache comparison command, from AgentHub (use the previous source revision after
committing the changes):

```powershell
@'
import json, statistics, subprocess, time, types
from unittest.mock import Mock
from app.cache import semantic_cache as current
previous = types.ModuleType('previous_cache')
exec(subprocess.check_output(['git', 'show', '8dfe7d9:app/cache/semantic_cache.py'], text=True), previous.__dict__)
vector = [0.01] * 1536
raw = json.dumps([dict(embedding=vector, meta=dict(top_k=5, provider='p' if i == 63 else 'other', model='m'), payload=dict(answer='answer', sources=[]), ts=time.time()) for i in range(64)])
for label, module in [('before', previous), ('after', current)]:
    client = Mock()
    client.get.return_value = raw
    module._redis = lambda: client
    samples = []
    for i in range(60):
        start = time.perf_counter()
        assert module.get_cached_rag_answer('q', vector, top_k=5, provider='p', model='m')['answer'] == 'answer'
        samples.append((time.perf_counter() - start) * 1000)
    print(label, 'median_ms', round(statistics.median(samples), 2), 'p95_ms', round(sorted(samples)[56], 2))
'@ | .venv/Scripts/python.exe -
```

## Security and dependency checks

All five local virtual environments were audited. AuthFortress used stdout;
the other four saved reports in their ignored virtual environments:

```powershell
uvx --from pip-audit pip-audit --path .venv/Lib/site-packages
uvx --from pip-audit pip-audit --path .venv/Lib/site-packages --format json --output .venv/audit-20261009.json
```

Final result: no known advisories. Initial AgentHub findings concerned outdated
local pip; it was updated to 26.2.1, matching the existing Dockerfile minimum.
Initial WebHook findings were stale python-jose/ecdsa packages absent from the
current manifest and running image. Reinstalling editable project metadata with
`uv pip install --python .venv/Scripts/python.exe --no-deps -e .`, removing those
two unused packages and `uv pip check` restored consistency. Duplicate advisory
rows were not counted as distinct vulnerabilities. This audit is not an OS image
scan or proof of absence of unknown vulnerabilities.

The five generated WebHook egg-info files were removed from Git tracking (they
already match `.gitignore`); generated local metadata remains on disk. This
prevents stale dependency declarations from returning in fresh checkouts.

Security review preserved identity/owner checks, HMAC and header filtering.
AuthFortress Bandit medium/high scan passed. Existing observability Bandit
findings and unauthenticated surfaces are not represented as a clean security
bill. No credentials or environment files were added to commits.

## Open boundaries and next stages

### Legacy delivery claim continuation

Three regressions reproduced simultaneous duplicate HTTP and mutation of an
active delivery by replay with inconsistent task references. WebHook Manager
now locks the delivery row before inspecting state; delivering returns without
HTTP or mutation. Claim commit releases the lock before HTTP. Pending, failed
and retrying behavior remains compatible. No schema or dependencies changed.

Full suite: 329 passed in 32.17 seconds, 85.24% coverage; Ruff and strict Mypy
(118 files) passed. Fresh adversarial/security review: 14 worker tests passed
in 16.36 seconds. In-memory mutations removing the guard or row lock failed
their corresponding regressions; removing the lock caused two HTTP sends.

Checks used an isolated tmpfs PostgreSQL `webhook_claim_test` at port 59629 and
Redis at 59630. From `D:/Programming/WebHook_Manager` with explicit
`TEST_DATABASE_URL`/`TEST_REDIS_URL` selecting those services:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m pytest tests/integration/test_worker_delivery.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/ --cov=src --cov-report=term --cov-fail-under=80
.venv/Scripts/python.exe -m ruff check src/ tests/ scripts/ alembic/
.venv/Scripts/python.exe -m mypy src/ --strict
docker build -f .venv/module-audit.Dockerfile -t webhook-delivery-claim:20261009 .
```

The image reuses the existing audited dependency base and has digest
`sha256:e4008fbd1501b900b9ddcc6e96fe601731853546c1b7c06f9796faead45f6013`.
The retained root override selects it for API/worker; Compose config and
`up -d --no-deps --no-build --wait --wait-timeout 120 webhook_service webhook_worker`
passed. From NexusCore, `../AgentHub/.venv/Scripts/python.exe scripts/verify_stack.py`
passed real health/auth/upload/webhook checks; Celery inspect ping returned pong.
Known legacy JWT/Telegram-to-AgentHub gaps reported by that script remain.
The controlled Telegram/AI chain was not rerun for this legacy-only change.
Temporary claim-test containers were stopped and auto-removed; root data volumes
and unrelated running services were preserved. `git diff --check` passed.

A lost worker leaves delivering visible and must not trigger automatic resend:
the external effect may already exist. Endpoint-wide concurrent counters,
broker recovery, ambiguous HTTP outcomes and SSRF remain separate work.

### EventPipe checkpoint and remaining platform work

EventPipe continuation: the user applied the SeaweedFS workflow replacement;
`79ab8dd` and GitHub run `37894123954` closed the failed CI gate. The isolated
`eventpipe-ci-check` stack was rebuilt and its complete smoke passed twice
using `.venv/Scripts/python.exe -m scripts.verify_eventpipe`; the second run
took 6.60 seconds. REST/batch/gRPC, repeated event identity, normalization,
PostgreSQL/query, S3 raw bytes and public-host SigV4, invalid/not-found paths
and real Kafka DLQ passed. The previous transform startup blocker did not recur.
All six healthchecked services were healthy; Zookeeper was running.
Local Debian HTTP 503 and pip resolution failures required unchanged build
retries. No source/dependency changes were needed for the successful builds.
These functional checks do not establish sustained load or tenant isolation.
The independent reviewer repeated the smoke successfully (6.85 seconds) and
approved the evidence. Three rebuilt images exclude `.env`, `.git` and `.venv`.
Test containers/network were removed with Compose `down`; volumes were retained.

1. Legacy webhook delivery still needs broker-publication recovery,
   reconciliation of interrupted claims/ambiguous outcomes, endpoint-wide concurrent
   failure counters and an egress/SSRF policy. A saved success
   is protected, but arbitrary external delivery is not exactly-once.
2. Legacy AgentHub RAG/documents/cache/usage lack tenant scope; cache lacks document
   invalidation. Platform job/usage metadata reads are scoped separately. Do not
   expose legacy endpoints as tenant-safe APIs.
3. PipeWatch management/callbacks and EventPipe lack shared identity and tenant
   filtering; callbacks permit private destinations. PipeWatch queue, alert rules
   and history are volatile. Observability is not yet connected to NexusCore.
4. VPS/domain/TLS, backups and restore drills, live OAuth, sustained load, full
   local clean image builds and public deployment were not verified (the separate
   five-service GitHub builds above and EventPipe local builds passed). Buying a VPS and
   domain alone does not complete these application/security requirements.

No migrations or dependencies were added. Existing migration upgrades/schema
checks passed during isolated chain setup; downgrade was not repeated. Temporary
test containers were removed after checks; test PostgreSQL used tmpfs and runtime
volumes remain intact.
