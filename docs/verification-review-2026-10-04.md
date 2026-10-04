# Reviewer and Critic — 2026-10-04

Reviewer: **APPROVE minimal patches**, no unresolved new regression found. Full
public/platform acceptance remains blocked. Reviewer independently ran Auth48selected
tests/Ruff/Mypy35, WH67full/83.07%/Ruff/Mypy87, AH4real infrastructure tests after
failure-handler fix, EP26full/built ETL smoke, PW20full/built HTTP/WS/CLI smoke.
Exact commands/results: `verification-final-2026-10-04.md` and sibling checkpoints.
Reviewers and Critic made no source edits or destructive/production operations.

Critic was invoked because Reviewer rated anonymous AgentHub access Critical.
Critic confirms the defect but rates it High for public/multi-tenant deployment;
Critical impact would require established exposure/sensitive data. Public shipment
recommendation remains **DO NOT SHIP**. Local patch approval is not public acceptance.

| Finding | Critic verdict | Evidence | Severity |
|---|---|---|---|
| AH anonymous/unscoped resources | CONFIRMED | Anonymous GET38082 `/api/v1/documents`:200; `../AgentHub/app/api/v1/documents.py:55`, conversations.py:30, retriever.py:17 | High |
| AH global semantic cache | CONFIRMED | `../AgentHub/app/cache/semantic_cache.py:56,124`, rag_pipeline.py:38: no authorized tenant/bot/corpus key | High |
| EP anonymous reads/raw download grant | CONFIRMED | Anonymous GET38085 `/api/v1/events`:200; query_service/app/api/events.py:57,84,104: unscoped reads/presign | High |
| PW anonymous logs/WS/alerts | CONFIRMED | Anonymous GET38084 `/api/v1/alerts`:200; app/main.py:125, ws/live_tail.py:19,68, api/v1/alerts.py:57 | High |
| PW callback SSRF | CONFIRMED code path | app/api/v1/alerts.py:22 accepts arbitrary target; services/alert_engine.py:111,133 posts it | High |
| WH endpoint SSRF | CONFIRMED code path | Router imports plural schemas/endpoints.py with unrestricted url:str:11; deliver_webhook.py:108 sends it | High |
| WH credential URL logging | CONFIRMED code path | deliver_webhook.py:131,166 logs unrestricted endpoint.url with possible userinfo/query secrets | Medium |
| WH concurrent dedup | CONFIRMED code path | services/event_service.py:29 lookup/create; db/models/webhook_event.py:44 and initial migration:250 contain nonunique indexes | High |
| WH durable publication gap | CONFIRMED code path | Router ingest.py:124 background task; dispatcher.py:41 commits before publish:42; duplicate skips dispatch | High |
| WH concurrent delivery | CONFIRMED code path | deliver_webhook.py:47–84 has no lock/atomic claim; DELIVERING does not exclude another sender | High for non-idempotent downstream effects |
| WH manual retry/dispatch | CONFIRMED code path | routers/deliveries.py:48,80; services/delivery_service.py:80–106 creates rows without enqueueing | Medium |
| WH first key bootstrap | CONFIRMED code path | routers/auth.py:53 login returns ID only; key creation:63 needs an existing key | Medium |

The public probes were read-only; no internal SSRF request or concurrent destructive
DB test was performed by Critic. Raw-object access was traced, not fetched by Critic.

Critic additionally highlighted:

- WH dispatch only loads100subscriptions: services/event_service.py:64 and
  subscription_repository.py:47–54; remaining matching subscriptions receive no task.
- AH upload reads full content without size/quota guard: api/v1/documents.py:38.
- AH document deletion leaves semantic cache populated: documents.py:68–74 and
  rag_pipeline.py:38. Answers/sources can remain cached until expiration.
- WH public HMAC ingress bypasses rate limit if API-key header is omitted:
  api/v1/dependencies/rate_limit.py:14–15.

Meaningful regression spot-check: AH tests/test_infrastructure.py:132–182 coordinates
real independent sessions, rollback and completed retry before failure handler proceeds.
Removing ready-state guard in embed_worker.py:72 breaks the intended assertion.
Reviewer reran4integration tests; Critic inspected this test without claiming a rerun.

Reviewer also independently diagnosed PW clock skew via POST and bounded-time query:
stored timestamp was1.884seconds ahead of host, unfilteredtotal1, host-end filtertotal0.
Bounded smoke wait fixes verification; actual CLI time filter semantics are preserved.

No need to reopen resolved AH-R1 or malformed HMAC findings: final narrow fixes and
test/build evidence pass. Full lint, tenant authorization and reliable delivery must
be implemented separately before platform shipment.
