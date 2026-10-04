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
docker compose config
docker compose up -d --build
docker compose ps
```

The root stack exposes PostgreSQL on `localhost:25432`, Redis on `localhost:26379`, AuthFortress at `http://localhost:28080/docs`, WebHook Manager at `http://localhost:8001/docs`, and AgentHub at `http://localhost:8014/docs`. These ports and credentials are for local development. Do not expose this Compose setup as a production deployment.

For service-specific setup and tests, use the README in each service repository. EventPipe and PipeWatch are not started by the root Compose file.

## Verification status

As of 2026-10-04, isolated service suites reported 256 passing tests: AuthFortress 128, WebHook Manager 67, AgentHub 15, EventPipe 26, and PipeWatch 20. These checks cover individual services and local dependencies; they do not certify the integrated platform. EventPipe still reports 13 Ruff findings.

Tenant isolation is not implemented across the platform. WebHook delivery recovery and egress restrictions remain open, and no public deployment or complete cross-service flow has been verified. Treat NexusCore as a development demo workspace, not a production-ready multi-tenant service.

## Next work

1. Define tenant identity and authorization contracts shared by the services.
2. Make webhook admission and delivery idempotent and recoverable after broker or worker failures.
3. Verify the Telegram → WebHook Manager → AgentHub → Telegram flow against those contracts.
4. Connect the event and log pipelines, then build the dashboard and deployment setup.
