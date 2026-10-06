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

AuthFortress and WebHook Manager apply their existing forward Alembic migrations before starting their APIs. AgentHub keeps legacy table creation for standalone startup; its opt-in Telegram mode requires an explicitly migrated platform schema. Database initialization runs only when the PostgreSQL volume is first created. AgentHub API and worker share an uploads volume.

For service-specific setup and tests, use the README in each service repository. EventPipe and PipeWatch are not started by the root Compose file.

## Verification status

### Free AI providers

Current Compose selects Groq and forwards `GROQ_API_KEY` to AgentHub. Groq API
authentication/model availability and direct generation through Gemini
`gemini-2.5-flash`, OpenRouter `liquid/lfm-2.5-2.6b:free` and Cloudflare Workers AI
`@cf/meta/llama-3.2-3b-instruct` were checked on 2026-10-06. OpenRouter reported
zero cost; the operator confirmed Gemini Free Tier and Workers Free.

OpenRouter and Cloudflare have no AgentHub adapter yet. Their reserved root
`.env` names are `OPENROUTER_TOKEN`, `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID`; Compose does not forward or activate them yet. Gemini's
existing adapter uses `GEMINI_API_KEY` in standalone AgentHub.

Stay on free accounts/models and keep paid fallback disabled.
[OpenRouter Free](https://openrouter.ai/pricing) has a 50-request daily limit;
[Workers Free](https://developers.cloudflare.com/workers-ai/platform/pricing/)
provides 10,000 Neurons/day. [Gemini limits](https://ai.google.dev/gemini-api/docs/rate-limits)
depend on project/model. Quota exhaustion must not trigger paid inference.
Token-price estimates and actual billed cost are different measurements.

The [approved AI/reply contract](specs/telegram-ai-reply.md) starts with Groq and
durable scoped jobs. UI token onboarding is planned separately with tenant-scoped
encryption and masked metadata. Direct probes do not prove Telegram -> AI -> reply.

### Service and integration checks

As of 2026-10-04, isolated service suites reported 256 passing tests: AuthFortress 128, WebHook Manager 67, AgentHub 15, EventPipe 26, and PipeWatch 20. These checks cover individual services and local dependencies; they do not certify the integrated platform. EventPipe still reports 13 Ruff findings.

On 2026-10-05, AuthFortress tenant creation, membership permissions and access isolation were verified through 43 tenant tests and the root HTTP service. Its complete regression suite passed 171 tests; Ruff and Mypy passed. Fresh migration upgrade, downgrade/upgrade and schema checks passed in a separate empty test database. Local evidence: `docs/verification-tenants-2026-10-05.md`.

On 2026-10-06, opt-in Telegram provisioning, authenticated intake and durable
publication were verified in WebHook Manager: 238 tests passed, coverage 84.03%,
Ruff/strict Mypy passed, and the migration roundtrip passed in a separate empty
test database. Controlled Docker acceptance used real AuthFortress JWT/owner
authorization, synthetic Telegram setup, Redis/Celery and a durable admission
receiver. It covered admission during broker outage, scanner recovery and a lost
receipt replay with one remote job. See [the intake contract](specs/telegram-ingress.md).

The API requires `PLATFORM_TELEGRAM_ENABLED`, a public HTTPS
`TELEGRAM_WEBHOOK_ORIGIN` and independent service keys. The optional
`telegram-ingress` Compose profile starts the recovery scanner; workers/scanner
do not receive the bot credential encryption key. Defaults remain disabled.
AgentHub's matching signed admission endpoint was verified on 2026-10-06:
79 tests passed; controlled built-image HTTP checks covered signature rejection,
202/200/409 receipts, durable PostgreSQL storage and UUID-only Redis notifications.
The bot-context HTTP boundary used synthetic data. Platform AI processing,
recovery scanners and Telegram answer delivery remain pending; root Compose does
not yet enable the new AgentHub mode. Enable live publication only after the
remaining contracts are implemented and verified.

Tenant isolation is not implemented across the entire platform. Legacy webhook
delivery recovery/egress restrictions, public deployment and the complete
Telegram/AI/reply scenario remain open. NexusCore is a development demo workspace.

The root stack smoke check requires Python 3.12 or newer and the running Compose stack:

```powershell
python scripts/verify_stack.py
```

It verifies root API health, AuthFortress login/JWT/protected-route rejection paths, AgentHub upload/worker/storage, and signed synthetic ingress through the real WebHook Redis/Celery worker to a controlled local receiver. It creates and retains uniquely named demo records and performs no live Telegram or LLM calls. First API-key/source provisioning uses the existing repository layer inside the webhook container because public onboarding is incomplete.

A passing root smoke still reproduces three gaps in the standalone route it uses
(the opt-in platform intake has separate controlled acceptance):

- WebHook Manager requires its own API key and rejects an AuthFortress bearer JWT with 401.
- Signed ingress requires `X-Webhook-Signature` HMAC; Telegram's secret-token header alone returns 401.
- Delivery preserves the Telegram JSON fields, but AgentHub `/api/v1/query` requires `question` and returns 422 for that payload. Delivery does not send the generated answer to Telegram.

## Next work

1. Implement bounded Groq generation and durable tenant/bot-aware processing
   with recovery under the [AI/reply contract](specs/telegram-ai-reply.md).
2. Implement durable answer delivery, then verify the live Telegram → AI → reply flow.
3. Close legacy delivery recovery/egress restrictions and platform-wide isolation.
4. Connect the event/log pipelines, dashboard and deployment setup.
