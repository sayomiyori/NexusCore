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

EventPipe and PipeWatch provide separate event and log pipelines. The opt-in Telegram → Groq → Telegram path was verified in an isolated live demo on 2026-10-08. Tenant authorization is implemented in opt-in service modes; connecting the event/log services to the root remains planned. The recorded 2026-10-13 local root release kept platform modes and live traffic disabled.

## Local development

Keep the repositories side by side because the root Compose file uses sibling directories as build contexts:

```text
workspace/
├── NexusCore/
├── AuthFortress/
├── WebHook_Manager/
└── AgentHub/
```

For a fresh stack with empty volumes, install Docker Desktop with Compose and
clone those repositories into the layout above. Run these commands from
`NexusCore` in PowerShell. Existing data needs its own checked migration procedure;
the updated local host uses the pinned restart procedure below.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env and set local credentials before starting the services.
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Invalid Compose configuration' }
docker compose build auth_service webhook_service webhook_worker agent_service agent_worker
if ($LASTEXITCODE -ne 0) { throw 'Image build failed' }
docker compose up -d --wait --wait-timeout 180 postgres redis
if ($LASTEXITCODE -ne 0) { throw 'Infrastructure startup failed' }
docker compose run --rm --no-deps --entrypoint python agent_service -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'AgentHub migration failed' }
docker compose up -d --no-build --pull never --wait --wait-timeout 180 auth_service webhook_service webhook_worker agent_service agent_worker
if ($LASTEXITCODE -ne 0) { throw 'Application startup failed' }
docker compose ps
```

The root stack binds its published ports to `127.0.0.1`: PostgreSQL on `localhost:25432`, Redis on `localhost:26379`, AuthFortress at `http://localhost:28080/docs`, WebHook Manager at `http://localhost:8001/docs`, and AgentHub at `http://localhost:8014/docs`. These ports and credentials are for local development. Do not expose this Compose setup as a production deployment.

Set both signing secrets to independent random values of at least 32 characters. Use URL-safe local database credentials because Compose interpolates them into connection URLs. Groq credentials are optional for startup and required for real generation. Embedding availability and provenance depend on the selected AgentHub revision; consult its configuration and migration contract before indexing. The historical local release used deterministic fallback embeddings, which do not verify semantic retrieval quality.

In this fresh-stack setup, AuthFortress and WebHook Manager apply forward Alembic
migrations before starting their APIs. AgentHub requires the explicitly migrated
resource schema even in standalone mode; startup table creation cannot replace
that migration. Database initialization runs only when the PostgreSQL volume is
first created. AgentHub API and worker share an uploads volume. Existing uploads
must grant UID/GID 10001 access before running the new images; ownership changes
require a separate inventory and approval.

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

### Published source checkpoints — 2026-10-31

The dashboard includes tenant reads, bot registration, webhook preparation,
knowledge indexing status and persisted tenant/bot AI model settings. See
[the unified release](docs/unified-release-2026-10-27.md),
[bot registration](docs/dashboard-bot-registration-2026-10-29.md) and
[webhook preview](docs/dashboard-webhook-preview-2026-10-29.md).
Later source hardening is recorded in
[Stage E acceptance](docs/security-hardening-stage-e-2026-10-30.md),
[runtime hardening](specs/runtime-hardening.md) and
[supply chain hardening](specs/supply-chain-hardening.md).
Source publication and isolated acceptance do not establish adoption by the
existing local deployment. Fresh root tooling checks are documented in
[local checks](docs/local-checks.md).

### Historical applied local release — 2026-10-13

The recorded local acceptance covers **989 distinct tests**: AuthFortress 196,
WebHook Manager 391, AgentHub 275, EventPipe 57 and PipeWatch 70. Configured
Ruff/Mypy checks, isolated migration roundtrips, tenant isolation, worker recovery,
built-image checks and independent reviews passed before the approved release.
These are dated results, not a fresh CI run or production-readiness claim.

The approved local update advanced WebHook to `8f3b1c6d2a90` and AgentHub to
`003_tenant_resources`; AuthFortress remained at `004_tenants`. Previous data and
metadata were preserved, legacy tenant assignments remain NULL, and the shared
uploads volume received UID/GID 10001 while retaining file hashes and modes.
The six selected application processes passed post-update checks. Telegram,
provider and MCP traffic stayed closed. EventPipe/PipeWatch stayed standalone.
This is a historical local receipt; the detailed operator report is retained
locally as `docs/local-service-hardening-2026-10-12.md` and is not published.

For that recorded deployment, retain all four local overrides in exactly this order;
the hardening override must be last. They are local operational files, absent
from a fresh clone. Validate without printing resolved environment values:

```powershell
$NexusComposeArgs = @(
  'compose', '-f', 'docker-compose.yml',
  '-f', '.venv/root-adoption.compose.yml',
  '-f', '.venv/root-auth-update.compose.yml',
  '-f', '.venv/root-delivery-recovery.compose.yml',
  '-f', '.venv/root-local-hardening.compose.yml', '--profile', 'legacy-recovery'
)
docker @NexusComposeArgs config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Invalid pinned Compose configuration' }
docker @NexusComposeArgs ps
```

After approval of the selected restart, use the same arguments and explicit
services. Revalidate configuration immediately before the restart:

```powershell
docker @NexusComposeArgs config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Invalid pinned Compose configuration' }
docker @NexusComposeArgs up -d --no-build --pull never --no-deps auth_service webhook_service webhook_worker webhook_delivery_recovery agent_service agent_worker
```

Do not use the original Compose file alone or rebuild implicitly against this
host's existing data. Application restart is separate from migration, upload
ownership changes and live activation. Backups were restored on isolated copies;
their Windows-user encryption does not establish cross-host recovery. Public
TLS/VPS, real OAuth/provider quality, OS-image vulnerability scanning and
production capacity remain unverified.

### Historical module checkpoint — 2026-10-09

At this historical checkpoint, service suites totalled **823 tests** (AuthFortress 192,
WebHook Manager 329, AgentHub 250, EventPipe 27, PipeWatch 25). Full configured
Ruff checks and applicable CI Mypy scopes passed. Fresh independent reviews
approved the scoped fixes after regression tests. The rebuilt local API/worker
stack, controlled Telegram/AI/reply chain and restricted nginx edge passed.

See [commands, performance measurements and remaining boundaries](docs/module-verification-2026-10-09.md).
The checkpoint covers modules as of that date; it does not establish public deployment,
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

The base Compose file defaults to Groq and forwards `GROQ_API_KEY` to AgentHub;
the updated host's final override empties provider credentials.
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

AgentHub requires resource Alembic head before standalone or enabled startup. For a fresh empty
AgentHub database, run `docker compose run --rm --no-deps --entrypoint python agent_service -m alembic upgrade head`
after the database exists. An existing legacy database first
requires comparison against the explicit legacy baseline and an approved baseline
procedure; do not blindly stamp or upgrade it. Root Compose does not assign a
baseline revision to existing data. WebHook Manager applies forward migrations
before API startup.

For a separately provisioned fresh stack, validate with
`docker compose --profile telegram-ai config --quiet`. Enabling live features on
the updated host requires a separately reviewed configuration and activation;
the pinned restart above keeps them disabled. Controlled tests alone do not
authorize live publication.

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
remained disabled; no root live AI flow was enabled. Those revisions and image
pins were subsequently replaced by the approved 2026-10-13 release above; use its
complete override order for the updated host.

On 2026-10-11, the separately approved
[legacy delivery recovery rollout](docs/legacy-recovery-rollout-2026-10-11.md)
advanced WebHook to `6e2f8a1c9b04`, replaced only its API/worker and started the
opt-in `webhook_delivery_recovery` scanner. Fresh encrypted backup/restore and
forward migration rehearsals passed; all old rows/schema/sequences/owners/ACLs
were preserved. The worker responds to ping, the scanner is idle with an empty
queue, API health/refusal checks pass and other root containers are unchanged.
Inspect legacy pending destinations before future scanner activation, even when
platform live flags are off.

The 2026-10-13 service acceptance supersedes the earlier isolation and legacy
egress gaps. Root event/log integration and public deployment remain planned.
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

1. Keep live features disabled until a separately approved activation and current
   [AI/reply flow](specs/telegram-ai-reply.md) acceptance.
2. Verify public deployment, portable/off-host recovery and capacity when the
   required infrastructure and access are available.
3. Connect the event/log pipelines only as separately requested
   roadmap work.

The first platform read increment is implemented in AgentHub:
[tenant-authorized AI job metadata and usage](specs/platform-ai-read.md).
It uses fresh AuthFortress and bot-context checks and excludes private message
content. `PLATFORM_READ_ENABLED` stays false by default. Tenant document/RAG,
conversation, usage and cache isolation are implemented and covered by the
2026-10-13 service acceptance. Persisted tenant/bot model selection is covered
by the later [AI settings contract](specs/tenant-ai-settings.md); live provider
activation remains separately authorized work.
