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

EventPipe and PipeWatch provide separate event and log pipelines. The opt-in Telegram → Groq → Telegram path was verified in an isolated live demo on 2026-10-08. Platform-wide identity enforcement and the event/log integration remain incomplete.

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

For a bounded loopback GET probe, use an environment with the existing `httpx`
dependency, for example the WebHook Manager virtualenv:

```powershell
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_local_load.py http://127.0.0.1:28080/health --duration 5 --concurrency 4
../WebHook_Manager/.venv/Scripts/python.exe -m unittest discover -s tests -p test_verify_local_load.py -v
```

The probe permits only loopback health endpoints or `/api/v1/auth/me`, uses no
proxy or redirects, and caps duration and concurrency. Auth requests can append
audit records. The results describe this local probe, not production capacity.

## Verification status

### Current module checkpoint — 2026-10-09

Latest verified service suites total **823 tests** (AuthFortress 192,
WebHook Manager 329, AgentHub 250, EventPipe 27, PipeWatch 25). Full configured
Ruff checks and applicable CI Mypy scopes passed. Fresh independent reviews
approved the scoped fixes after regression tests. The rebuilt local API/worker
stack, controlled Telegram/AI/reply chain and restricted nginx edge passed.

See [commands, performance measurements and remaining boundaries](docs/module-verification-2026-10-09.md).
The checkpoint covers current modules; it does not establish public deployment,
tenant-safe legacy RAG, observability integration or exactly-once legacy delivery.
Post-push CI passed for all five services. EventPipe now uses its existing
SeaweedFS test Compose; all 27 tests, zero-skip enforcement and three Docker
builds passed in [run 37894123954](https://github.com/sayomiyori/EventPipe/actions/runs/37894123954).
The rebuilt EventPipe standalone stack also passed its complete REST/gRPC-to-query
smoke twice, including S3 signatures and real Kafka DLQ.
The latest WebHook continuation serializes claims for one delivery in PostgreSQL
and makes delivering replays a no-op; three new regressions and the complete
WebHook suite passed. Interrupted claims require outcome reconciliation.

### Free AI providers

Current Compose defaults to Groq and forwards `GROQ_API_KEY` to AgentHub.
`LLM_PROVIDER` and `LLM_MODEL` configure the standalone API and worker together;
the opt-in Telegram path retains its separate `TELEGRAM_AI_MODEL`. Groq API
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
The bot-context HTTP boundary used synthetic data. Durable AI processing, signed
answers and Telegram sending are now implemented in the sibling services;
controlled acceptance does not prove live delivery. The `telegram-ai` profile
adds dedicated generation/reply/send workers and independent recovery scanners.
All platform flags remain disabled by default.

Enable `PLATFORM_BOTS_ENABLED`, `PLATFORM_TELEGRAM_ENABLED`,
`TELEGRAM_AI_ENABLED` and `TELEGRAM_REPLIES_ENABLED` only with a public HTTPS
webhook origin, bot credential encryption key, Groq credentials/model and
independent issuer/context/ingress/reply keys. AgentHub receives no Telegram
credential encryption key. Platform workers consume dedicated `telegram_ai`,
`telegram_replies` and `telegram_send` queues; legacy workers keep their queues.

AgentHub requires platform Alembic head before enabled startup. For a fresh empty
AgentHub database, run `docker compose run --rm --no-deps agent_service python -m alembic upgrade head`
after the database exists. An existing legacy database first
requires comparison against the explicit legacy baseline and an approved baseline
procedure; do not blindly stamp or upgrade it. Root Compose does not assign a
baseline revision to existing data. WebHook Manager applies forward migrations
before API startup.

Validate with `docker compose --profile telegram-ai config --quiet`; after the
schema prerequisite and separately approved live provisioning, start with
`docker compose --profile telegram-ai up -d --build --wait`. Controlled tests
alone do not authorize live publication.

For isolated controlled acceptance, use WebHook Manager's existing virtualenv
and locally cached images. No external test database or host ports are needed:

```powershell
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_telegram_ai.py
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_telegram_ai.py --scanners
```

Both commands own fresh internal Compose fixtures, use actual issuer/tenant/bot
APIs, PostgreSQL and Celery, and intercept only synthetic Telegram/Groq effects.
The AI fixture stops before the separate standalone acceptance starts. Scanner
mode exercises the five real permanent recovery loops, owned PostgreSQL/broker
outages, lost queue notifications and bounded automatic process restart.
No real credentials, Telegram setup, provider inference or existing root data
are used. See [isolated smoke and scanner acceptance](docs/isolated-smoke.md) for
commands, ownership guards, receipt fields and verification limits.

On 2026-10-07, this full controlled chain and the reused standalone stack smoke
passed, including document upload/embedding storage and legacy webhook delivery.
AgentHub's complete regression passed 177 tests; WebHook Manager passed 311 tests
with 84.90% coverage. Both migration heads were verified in fresh databases;
the new WebHook migration roundtrip passed in a separately approved empty test
database. Fresh read-only adversarial/security review approved the integration.
At that checkpoint, existing root data had not been migrated for live AI delivery.

On 2026-10-08, a separately approved live run used real Telegram intake, native
workers/scanners and Groq `openai/gpt-oss-20b`. Exactly one scoped job, usage
record, published reply and successful Telegram delivery were confirmed.
Generation, publication and sending each took one attempt. The public intake
closed after admission; Telegram
reported no pending updates. Independent read-only review confirmed the result.
This verifies one guarded demo flow, not production readiness or billed cost.

On 2026-10-08, the existing local root databases were adopted under a separately
approved procedure: AgentHub is at `002_telegram_ai` and WebHook Manager at
`3cc3bb772105`. Fresh encrypted backups were restored and migrated on isolated
copies before root writes. Legacy data, sequence state, ownership and privileges
were preserved. The four AgentHub/WebHook application processes now use the
verified images; API health and legacy worker pongs passed. AI/intake/reply flags
remain disabled; no root live AI flow was enabled. On the verified local host,
restart uses the retained `.venv/root-adoption.compose.yml`,
`.venv/root-auth-update.compose.yml` and `.venv/root-delivery-recovery.compose.yml`
overrides (not tracked, in that order) to pin the verified images and disabled
flags. The last override was added with the approved recovery rollout below:

```powershell
docker compose -f docker-compose.yml -f .venv/root-adoption.compose.yml -f .venv/root-auth-update.compose.yml -f .venv/root-delivery-recovery.compose.yml up -d --no-build --pull never --no-deps agent_service agent_worker webhook_service webhook_worker webhook_delivery_recovery
```

This command describes that host's deployment, not a fresh-clone setup. Do not
restart its old WebHook images against the new migration revision.

On 2026-10-11, the separately approved
[legacy delivery recovery rollout](docs/legacy-recovery-rollout-2026-10-11.md)
advanced WebHook to `6e2f8a1c9b04`, replaced only its API/worker and started the
opt-in `webhook_delivery_recovery` scanner. Fresh encrypted backup/restore and
forward migration rehearsals passed; all old rows/schema/sequences/owners/ACLs
were preserved. The worker responds to ping, the scanner is idle with an empty
queue, API health/refusal checks pass and other root containers are unchanged.
Inspect legacy pending destinations before future scanner activation, even when
platform live flags are off.

Tenant isolation is not implemented across the entire platform. Legacy webhook
egress restrictions and public deployment remain open.
NexusCore is a development demo workspace.

The standalone stack smoke uses a new internal fixture with owned test storage,
cached images, no host ports and an inspected numeric callback IP:

```powershell
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_stack.py
../WebHook_Manager/.venv/Scripts/python.exe scripts/verify_stack.py --scanners
```

It checks health, auth/JWT denials, upload/worker/storage, signed callbacks,
unsafe egress and sequential/concurrent admission. API-key/source provisioning
uses the fixture's existing repository layer because public onboarding remains
incomplete. Scanner mode additionally tests the real legacy delivery recovery
loop. All exits stop owned containers and retain credential-free receipts and
volumes. See [the isolated workflow](docs/isolated-smoke.md); existing root data,
WSL settings and live Telegram/LLM are outside these commands.

A passing root smoke still reproduces three gaps in the standalone route it uses
(the opt-in platform intake has separate controlled acceptance):

- WebHook Manager requires its own API key and rejects an AuthFortress bearer JWT with 401.
- Signed ingress requires `X-Webhook-Signature` HMAC; Telegram's secret-token header alone returns 401.
- Delivery preserves the Telegram JSON fields, but AgentHub `/api/v1/query` requires `question` and returns 422 for that payload. Delivery does not send the generated answer to Telegram.

## Next work

The optional [Telegram demo edge](docs/telegram-demo.md) provides a restricted
Cloudflare origin for one registered bot. It includes an isolated nginx acceptance
check and explicit preparation/cleanup instructions. It does not install a
webhook or enable the root AI flow.

1. Define a separately approved root opt-in acceptance before enabling the
   verified [AI/reply flow](specs/telegram-ai-reply.md) there; schema adoption is complete.
2. Close legacy egress restrictions and platform-wide isolation.
3. Connect the event/log pipelines, dashboard and deployment setup.

The first platform read increment is implemented in AgentHub:
[tenant-authorized AI job metadata and usage](specs/platform-ai-read.md).
It uses fresh AuthFortress and bot-context checks and excludes private message
content. `PLATFORM_READ_ENABLED` stays false by default; tenant RAG, cache and
AI configuration remain separate work.
