# NexusCore Project Map

Latest evidence: `docs/verification-final-2026-10-04.md`. Five local scenarios are
verified; full public/tenant acceptance remains blocked. Older pause notes are historical.

NexusCore is the integration and live-demo repository. Services remain independent sibling Git repositories under `D:/Programming`.

| Repository | Responsibility | Verification order |
| --- | --- | --- |
| `../AuthFortress` | Identity, sessions, RBAC, OAuth, TOTP | 1 |
| `../WebHook_Manager` | Webhook intake, idempotency, queued delivery | 2 |
| `../AgentHub` | LLM routing, retrieval, semantic cache, usage | 3 |
| `../EventPipe` | REST/gRPC ingestion, Kafka ETL, PostgreSQL/MinIO, query API | 4 |
| `../PipeWatch` | Event ingestion/query, live WebSocket tail | 5 |

Root Compose currently references AuthFortress, WebHook_Manager and AgentHub. Existing local changes in sibling repositories belong to the user.

Acceptance scope: `specs/service-verification.md`. Execution checklist: `docs/service-verification-plan.md`.

## Evidence at baseline (2026-10-03)

- AuthFortress: clean Git working tree; CI defines Ruff, Mypy, pytest and Docker build.
- AuthFortress fixtures use SQLite and FakeRedis, despite the README claiming PostgreSQL/Redis tests.
- AuthFortress audit middleware opens an independent database session outside dependency overrides.
- Docker Engine was unavailable at the start of verification.
- AuthFortress Python 3.12 environment created in its ignored `.venv` directory.

These observations do not certify any service as passing.

## Latest pause checkpoint

Verification expanded to all five services at the user's request and was paused
on 2026-10-03. Read `docs/verification-resume-2026-10-03.md` before resuming;
it supersedes older result counts and records outstanding checks and known failures.
