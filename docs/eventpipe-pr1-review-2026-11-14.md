# EventPipe PR #1 review — 2026-11-14

Status: **review complete; not approved for merge, and root observability Stage 1
runtime acceptance remains Blocked.** Two gates are open on the EventPipe side and
four are open on the root/environment side. No merge, no runtime profile, no
sibling branch change and no `.env` change was made by this review.

Vocabulary: **Verified** = reproduced in this session with a recorded command;
**Implemented** = present in the code and covered by an automated test but not
exercised against the root stack; **Blocked** = cannot proceed without a missing
decision, credential or rehearsal.

## 1. Artifact under review

| Field | Value |
| --- | --- |
| PR | [sayomiyori/EventPipe#1](https://github.com/sayomiyori/EventPipe/pull/1), draft |
| Head | `855a7a8deffe6f107b7278e0150d8582eb7c887e` (`wip/home-2026-11-14`) |
| Base | `9948626f5d1d186841e59972594d8fee307b9948` (`main`) |
| Diff | 53 files, +1510 / -132 |
| Mergeability | `MERGEABLE`, `mergeStateStatus=UNSTABLE` |
| CI | `lint-test-build` pass; `GitGuardian Security Checks` **fail** |

The diff was read from the preserved worktree `D:\Programming\EventPipe-wip-review`
(clean at `855a7a8`, equal to the PR head), not by mutating the sibling checkout
`D:\Programming\EventPipe`, which stays on `main`.

## 2. Commands used

```powershell
gh pr view 1 --repo sayomiyori/EventPipe --json number,title,state,isDraft,headRefOid,baseRefOid,mergeable,mergeStateStatus,additions,deletions,changedFiles
gh pr checks 1 --repo sayomiyori/EventPipe
gh run view 43629462838 --repo sayomiyori/EventPipe --log
git -C D:\Programming\EventPipe-wip-review diff 9948626 855a7a8
git -C D:\Programming\EventPipe-wip-review status --short --branch
docker exec nexus-auth python -c "from app.api.v1.tenants import authorize_tenant, AuthorizedContext; print('authorize_present', AuthorizedContext.model_fields.keys())"
docker compose config --quiet
docker compose --profile observability-events config --quiet
docker inspect -f '{{.Name}} created={{.Created}} started={{.State.StartedAt}}' nexus-auth nexus-postgres nexus-webhook-api
D:\Programming\NexusCore\.venv\tooling-checks\Scripts\python.exe -m unittest discover -s tests -p "test_verify*.py" -q
```

Observed:

- `gh pr checks`: `GitGuardian Security Checks fail` with output
  `1 secret uncovered!` — `1 secret was uncovered from the scan of 1 commit in
  your pull request`. GitGuardian publishes no annotation on this repository
  (`/check-runs/132552646704/annotations` returns `[]`), so the dashboard remains
  the authority for the exact line.
- `gh run view 43629462838`: Ruff `All checks passed!`, then **57 passed in
  9.81s** with the CI-enforced "integration tests must not be skipped" assertion,
  then three Docker builds. This supersedes the earlier local
  `52 passed, 5 skipped`; the five local skips were infrastructure tests that CI
  runs for real.
- `docker exec nexus-auth ...`: the running AuthFortress image (`65256ce`) exposes
  `POST /api/v1/tenants/{tenant_id}/authorize` with fields
  `user_id, tenant_id, role, permission, allowed` — the contract EventPipe calls.
- `docker compose config --quiet`: **exit 1**, 18 error lines, e.g.
  `required variable AUTH_DB_PASSWORD is missing a value` (same for
  `WEBHOOK_DB_PASSWORD`, `AGENT_DB_PASSWORD`).
- `docker inspect`: the running containers were created 2026-10-04…2026-10-12 and
  only restarted at `2026-11-14T18:07Z`. `fb1e077` (2026-10-30) introduced the
  per-service database passwords, so the running stack predates the committed
  Compose contract.
- Root suite: **189 tests, OK, exit 0**.

## 3. Verdict

The change itself is a coherent, well-tested platform-mode and tenant-boundary
increment and is the correct base for root Stage 1. It is **not mergeable today**
because one required check is red, and Stage 1 acceptance **cannot be run today**
because the root environment cannot render the committed Compose.

Merge is additionally gated by the explicit approval rule in the task: a clean
review is recorded here, but the merge is a separate decision.

## 4. What the change does, and what is credible in it

All of the following is Implemented and covered by tests; the runtime items marked
Verified were confirmed against the real AuthFortress contract in this session.

1. **Online authorization on every boundary.** `eventpipe/platform.py:9-46` calls
   AuthFortress for each REST and gRPC request, with no cache, no redirects,
   `trust_env=False`, a 5 s timeout and strict response validation
   (`allowed is True`, canonical `tenant_id` echo, `permission` echo, role in
   `owner|member`, owner required for `tenant.manage`, `user_id` parseable). Any
   transport/parse/status anomaly becomes 503; 401/403/404 pass through. The
   bearer shape is rejected before the call. **Verified** against
   `AuthFortress/app/api/v1/tenants.py`: `AuthorizedContext` fields match,
   `AuthorizationRequest` is `extra="forbid"` with a `tenant.manage` enum value,
   non-membership returns 404, member + manage returns 403.
2. **Tenant scoping on every read.** `query_service/app/api/events.py:63-64`
   scopes list, detail, raw and all three stats queries; the raw proxy additionally
   requires the `tenants/{tenant_id}/` key prefix (`:135-136`) and returns bytes
   with `Cache-Control: no-store`. `test_platform_storage.py:161-177` covers
   missing credential, cross-tenant detail/raw 404, selector mismatch 404 and
   per-tenant `dlq_count`.
3. **Server-derived tenant in the transport envelope.**
   `ingest_service/app/api/events.py:31-37,61` writes only the authorized tenant
   into the Kafka body; `EventIngest` is `extra="forbid"`, so a client-supplied
   `tenant_id` is a 422 (`test_platform.py:96-97`). gRPC mirrors this and
   regenerates the event ID in platform mode (`servicer.py:65-68`).
4. **Transform fail-closed.** `consumer.py:130-139` dead-letters a missing or
   malformed tenant in platform mode; `:141-180` rejects an `event_id` reused by a
   different tenant or with different bytes; `storage/postgres.py:27-48` never
   overwrites a tenant row and re-reads to prove identity.
   `db/session.py:21-25` refuses to start unless the head is `002_tenant_boundary`
   — no `create_all`, no silent schema drift.
5. **Migrations are safe and reversible with a guard.**
   `001_legacy_baseline` refuses any pre-existing table (`:14-16`);
   `002_tenant_boundary` adds a nullable `tenant_id`, a `raw_sha256`, a tenant
   index and a coordinate-keyed `failed_events`, and refuses to downgrade once a
   tenant-scoped row exists (`002:30-37`). The integration test proves
   upgrade → downgrade → upgrade on a fresh database, exact legacy adoption, and
   `compare_metadata(...) == []` drift (`test_platform_storage.py:50-101`).
6. **Sanitized dead letters.** `consumer.py:107-117` stores topic/partition/offset,
   error class, record hash and a valid tenant UUID only; the Kafka DLQ body carries
   that diagnostic, not the raw event. `test_consumer_failures.py` asserts the
   absence of secrets and that a failed DLQ publish does not commit the source
   offset.
7. **Bounded admission.** `body_limit.py` caps REST bodies at 1 MiB before JSON
   parsing; batch is capped at 1000 events; the producer publish is bounded to 5 s
   and maps broker failure to a sanitized 503 (`main.py:51-57`,
   `test_platform.py:157-164`).
8. **No tenant labels in metrics.** `events_ingested_total` lost its
   `source`/`event_type` labels, and the sibling Grafana dashboard only uses
   `sum(...)`, so no shipped panel breaks.

## 5. Blockers

### 5.1 EventPipe side

| ID | Blocker | Evidence | Remedy |
| --- | --- | --- | --- |
| B1 | Required check red: GitGuardian reports 1 secret in the PR commit | `gh pr checks 1` → `fail`, `1 secret uncovered!` | Remove the inline credential literals added with the two `migrate` services: `docker-compose.yml:173` and `docker-compose.test.yml:93` (`postgresql+asyncpg://eventpipe:…@postgres:5432/…`). Interpolate instead, mirroring `NexusCore` PR #29 (`${VAR:-}` plus a Compose secret and an operator-supplied URL). Re-run the check; the dashboard confirms the exact finding. |
| B2 | No approval; PR is draft | `isDraft=true` | Merge requires an explicit decision from the lead after B1 is green; the draft flag is not a defect. |

Both new credential literals use values that already existed elsewhere in the
repository, so this is a new *occurrence* rather than a new secret; it is still a
merge gate because the same class of finding closed `NexusCore` PR #28.

### 5.2 Root / environment side (Stage 1 acceptance)

| ID | Blocker | Evidence | Remedy owner |
| --- | --- | --- | --- |
| R1 | The committed root Compose cannot be rendered with the current `.env` | `docker compose config --quiet` → exit 1, `AUTH_DB_PASSWORD`, `WEBHOOK_DB_PASSWORD`, `AGENT_DB_PASSWORD` required by `fb1e077` but absent | Operator: add the three per-service passwords plus `EVENTPIPE_DB_PASSWORD`, `EVENTPIPE_DATABASE_URL`, `SEAWEEDFS_ACCESS_KEY`, `SEAWEEDFS_SECRET_KEY`, `NEXUS_EVENTS_TOKEN` to a rehearsed env source. Not done here: `.env` is not overwritten by this task. |
| R2 | The build context `../EventPipe` is on `main` `9948626`, which has no `alembic.ini`, no `migrations/`, no `eventpipe/` package and no platform settings | `git -C ../EventPipe log --oneline -1` = `9948626`; the profile builds `transform_service/Dockerfile`, which now `COPY`s `alembic.ini` and `migrations` | Merge PR #1, then fast-forward the sibling checkout (a change to a sibling repository, so it needs its own approval) |
| R3 | Activating the profile on the permanent stack needs explicit approval, and the permanent stack must keep its data | Task rule; `PROJECT-MAP.md` runbook | Separate approval record naming the scope and rollback owner |
| R4 | No short-lived owner JWT with owner membership in two tenants exists for the acceptance probes | `NEXUS_EVENTS_TOKEN` is empty in `.env`; no tenant A/B fixture is recorded | Operator, per `specs/root-observability-integration.md` §8.2 |

Until R1 and R2 are closed, `docker compose --profile observability-events up`
cannot build or start, so the Stage 1 exit gate cannot be exercised. Nothing in
this document should be read as a Stage 1 pass.

## 6. Findings to fix before or during acceptance

| ID | Finding | Severity |
| --- | --- | --- |
| F1 | Root `eventpipe_transform` does not depend on `eventpipe_migrate`. `init_db` refuses any head other than `002_tenant_boundary`, so a single `up` of the whole profile can crash-loop the worker until the one-shot job finishes; `--wait` may report failure. EventPipe's own `docker-compose.test.yml` already wires `migrate: service_completed_successfully`, and `docker-compose.yml:635-644` does not. | Medium — flaky acceptance, no data loss. Fix in `NexusCore/docker-compose.yml` with a static-gate assertion. |
| F2 | The root profile sets `METRICS_ENABLED=false` on all three EventPipe services, but EventPipe reads no such setting. `/metrics` stays available (no tenant labels, loopback/operational only). The variable is inert and misleading. | Low — contract/doc mismatch. |
| F3 | `EventIngest`/`BatchEventIngest` became `extra="forbid"`, and source/event_type gained `max_length` bounds. Legacy clients that sent undeclared fields now get 422. The relay payload is compatible, but the contract change needs a release note because `specs/local-hardening.md` claims the standalone REST contract is retained. | Low — intentional tightening, document it. |
| F4 | `events_ingested_total` lost its `source`/`event_type` labels. Shipped Grafana panels use `sum()` only, so nothing breaks; any external scrape using those labels will. | Low — document the metric contract change. |
| F5 | A tenant row whose object key is outside `tenants/{tenant_id}/` returns **503** from `/raw`, while a foreign row returns 404. Fail-closed, but the status conflates storage corruption with unavailability. | Low. |
| F6 | `publish_dlq` accepts `kafka_key` but always sends the literal key `invalid-event`. The DLQ topic has one partition, so the effect is nil; the parameter is dead. | Cosmetic. |
| F7 | Each gRPC streamed event re-authorizes against AuthFortress, and the first event of `IngestStream` is authorized twice (`servicer.py:98,107`). Correct, but it doubles the identity calls of the first message and adds one HTTP round-trip per event. | Low — latency only. |
| F8 | `init_db` pins the literal revision `002_tenant_boundary`. A future migration requires a transform code change before the worker can start. Intentional fail-closed; record it so nobody "fixes" it by loosening the check. | Informational. |
| F9 | The Kafka envelope carries the tenant only as a plain field; Kafka itself is unauthenticated on the internal network. Tenant integrity therefore depends on network isolation, not on broker authentication. | Informational — inside the documented demo boundary. |

No finding above changes the conclusion of §4: the tenant boundary is enforced at
every read and write path that the code exposes.

## 7. Stage 1 exit gate, item by item

| Gate from `specs/root-observability-integration.md` §7 | Status |
| --- | --- |
| `docker compose --profile observability-events config --quiet` | **Blocked** (R1) |
| All services healthy | **Blocked** (R1, R2, R3) |
| Migration head `002_tenant_boundary` | **Implemented**, not exercised in the root; the migration itself is Verified in EventPipe CI |
| Authorized POST/GET works | **Implemented**, Verified only against the EventPipe identity stub and the isolated fixture, not the root AuthFortress |
| Tenant B denied | **Implemented**, Verified in isolation; the real issuer path is contract-checked but not run |
| Kafka stop → 503 | **Implemented**, Verified in EventPipe CI and the sibling harness; not run in the root |
| Malformed event → DLQ with sanitized diagnostic | **Implemented**, Verified in EventPipe CI; not run in the root |
| Existing root containers, volumes and data unchanged | **Not applicable yet** — nothing was started |

## 8. Ordered next steps

1. Fix B1 inside the `wip/home-2026-11-14` branch (interpolated database URL in
   both Compose files), push, confirm GitGuardian and `lint-test-build` are green,
   and mark the PR ready.
2. Obtain the merge decision, merge PR #1, then fast-forward the sibling
   `../EventPipe` checkout with approval.
3. Fix F1 in `NexusCore/docker-compose.yml` and extend
   `tests/test_verify_root_observability_wiring.py` with the dependency assertion;
   re-run the 189-test suite, Ruff and both `compose config` modes with a rehearsed
   env source.
4. Prepare the rehearsed env source (R1) and the two-tenant owner JWT (R4) without
   touching the running stack's data.
5. Only then request approval to activate `observability-events` for the Stage 1
   run, and record each gate of §7 with the exact command and response.
