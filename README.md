# NexusCore

NexusCore is the integration workspace for independent services behind a Telegram bot management platform. Each service lives in its own repository and can be developed and run separately. This repository holds the root Docker Compose setup, database initialization, and project-level documentation; it does not contain the service implementations.

## Services

| Service | Responsibility | Repository |
|---|---|---|
| AuthFortress | Authentication, sessions, roles, OAuth, and two-factor authentication | [AuthFortress](https://github.com/sayomiyori/AuthFortress) |
| WebHook Manager | Telegram update intake and queued webhook delivery | [WebHook Manager](https://github.com/sayomiyori/WebHook_Manager) |
| AgentHub | LLM routing, document retrieval, semantic cache, and usage tracking | [AgentHub](https://github.com/sayomiyori/AgentHub) |
| EventPipe | Event ingestion, Kafka processing, storage, and query API | [EventPipe](https://github.com/sayomiyori/EventPipe) |
| PipeWatch | Log ingestion, ClickHouse queries, live tail, and alerts | [PipeWatch](https://github.com/sayomiyori/PipeWatch) |

The root Compose file builds AuthFortress, WebHook Manager, and AgentHub alongside PostgreSQL and Redis. EventPipe and PipeWatch have separate Compose setups in their repositories.

## Request flow

The intended product flow is:

```text
Telegram → WebHook Manager → Celery / Redis → AgentHub → Telegram
                  ↑
           AuthFortress identity
```

EventPipe and PipeWatch provide separate event and log pipelines. The diagram describes the target architecture; the complete Telegram-to-Telegram flow and shared identity integration have not been verified end to end.

## Local development

Keep the repositories side by side because the root Compose file uses sibling directories as build contexts:

```text
workspace/
├── NexusCore/
├── AuthFortress/
├── WebHook_Manager/
└── AgentHub/
```

Install Docker Desktop with Compose, clone those repositories into the layout above, then run these commands from `NexusCore` in PowerShell:

```powershell
Copy-Item .env.example .env
# Edit .env and set local credentials before starting the services.
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 180
docker compose ps
```

The root stack binds its published ports to `127.0.0.1`: PostgreSQL on `localhost:25432`, Redis on `localhost:26379`, AuthFortress at `http://localhost:28080/docs`, WebHook Manager at `http://localhost:8001/docs`, and AgentHub at `http://localhost:8014/docs`. These ports and credentials are for local development. Do not expose this Compose setup as a production deployment.

Set both signing secrets to independent random values of at least 32 characters. Use URL-safe local database credentials because Compose interpolates them into connection URLs. Groq credentials are optional for startup and required for real generation. Without a Gemini key, AgentHub uses its existing deterministic fallback embeddings; these do not verify semantic retrieval quality.

AuthFortress and WebHook Manager apply their existing forward Alembic migrations before starting their APIs. AgentHub uses its existing table creation on startup. Database initialization runs only when the PostgreSQL volume is first created. AgentHub API and worker share an uploads volume.

For service-specific setup and tests, use the README in each service repository. EventPipe and PipeWatch are not started by the root Compose file.

## Verification status

As of 2026-10-04, isolated service suites reported 256 passing tests: AuthFortress 128, WebHook Manager 67, AgentHub 15, EventPipe 26, and PipeWatch 20. These checks cover individual services and local dependencies; they do not certify the integrated platform. EventPipe still reports 13 Ruff findings.

Tenant isolation is not implemented across the platform. WebHook delivery recovery and egress restrictions remain open, and no public deployment or complete cross-service flow has been verified. Treat NexusCore as a development demo workspace, not a production-ready multi-tenant service.

The root stack smoke check requires Python 3.12 or newer and the running Compose stack:

```powershell
python scripts/verify_stack.py
```

It verifies root API health, AuthFortress login/JWT/protected-route rejection paths, AgentHub upload/worker/storage, and signed synthetic ingress through the real WebHook Redis/Celery worker to a controlled local receiver. It creates and retains uniquely named demo records and performs no live Telegram or LLM calls. First API-key/source provisioning uses the existing repository layer inside the webhook container because public onboarding is incomplete.

A passing smoke check also reproduces three integration gaps:

- WebHook Manager requires its own API key and rejects an AuthFortress bearer JWT with 401.
- Signed ingress requires `X-Webhook-Signature` HMAC; Telegram's secret-token header alone returns 401.
- Delivery preserves the Telegram JSON fields, but AgentHub `/api/v1/query` requires `question` and returns 422 for that payload. Delivery does not send the generated answer to Telegram.

## Next work

1. Review the draft [integration contracts](specs/integration-contracts.md), then implement the AuthFortress tenant foundation.
2. Make webhook admission and delivery idempotent and recoverable after broker or worker failures.
3. Verify the Telegram → WebHook Manager → AgentHub → Telegram flow against those contracts.
4. Connect the event and log pipelines, then build the dashboard and deployment setup.
