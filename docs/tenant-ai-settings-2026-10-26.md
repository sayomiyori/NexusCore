# Persisted tenant/bot AI settings acceptance — 2026-10-26

## Implemented

AgentHub now stores model selection for tenant defaults and bot overrides, with
effective precedence bot > tenant > operator platform. Provider remains Groq.
Null resets inheritance by appending a new revision, without deleting the record
or audit history. Every successful write stores the authorized actor and revision
atomically. SQL compare-and-swap rejects concurrent/stale versions with 409.

New GET/PUT `/api/v1/tenants/{tenant}/ai/settings` and bot-scoped `/ai/settings`
use fresh issuer ai.read / owner-only ai.configure; bot operations also resolve
fresh active context. Strict bounded duplicate-free input accepts only model and
expected_revision. No body scope, keys, processing flag or provider activation.
The existing process-policy `/ai/configuration` endpoint remains compatible.

The first job claim resolves the effective saved model and freezes it in the
job's existing fields. Retry retains that model after later settings edits.
The startup and generation paths now share the model-identifier validator:
invalid enabled operator models cannot create an unbounded pre-claim failure.
No real generation was used to verify this behavior.

Dashboard AI Configuration now supports tenant scope without bots and active
bot scope with paged inventory. Load precedes editing. Owners get Save model /
Use inherited model; members read only. Saved revision and effective source are
shown separately. Saving locks scope, organization, input, navigation, Refresh
and logout. Conflicts/unconfirmed writes clear the editor and require reload;
no automatic mutation retry. A success acknowledgement must match exactly the
requested model and next revision. Scope changes discard local drafts.

See [contract](../specs/tenant-ai-settings.md), [dashboard runbook](../dashboard/README.md)
and AgentHub `docs/tenant-ai-settings.md` for storage and HTTP details.
Backend commit: [e3e9839](https://github.com/sayomiyori/AgentHub/commit/e3e9839ddc5caf4adfe4a7da7f078fa35b80485e).

## Automated verification

Dashboard commands, from `dashboard/`:

```powershell
$env:NEXT_TELEMETRY_DISABLED='1'
npm test
npm run typecheck
npm run lint
npm run build
npm audit
npm audit --omit=dev
```

**56/56 passed**, including eight new settings BFF HTTP cases. These cover
tenant/bot projection, exact PUT acknowledgement, fresh owner/member checks,
CSRF/Host/session/query guards, duplicate/invalid/oversize JSON, safe409 handling,
one upstream write without retry, malformed revisions/dates/types/inheritance
and source failures. Strict TypeScript, Biome38, production build and both audits
passed; **0 vulnerabilities**. Existing read-only sections/routes remained green.

Backend commands, in the clean AgentHub worktree with isolated test URLs.
Migration commands use DATABASE_URL for a separate new empty database, not the
retained suite database or an existing stand:

```powershell
python -m alembic upgrade head
python -m alembic downgrade -1
python -m alembic upgrade head
python -m alembic check
python -m pytest tests/ -q -p no:cacheprovider
python -m ruff check .
python -m mypy app/models/llm_usage.py app/services/usage_tracker.py app/metrics.py app/cache/semantic_cache.py app/platform app/api/internal app/api/v1/platform_reads.py app/api/v1/ai_settings.py app/models/ai_settings.py app/db/platform.py app/models/telegram_job.py app/models/telegram_reply.py app/models/telegram_usage.py app/workers/telegram_worker.py app/workers/telegram_reply_worker.py scripts/recover_telegram_jobs.py scripts/recover_telegram_replies.py
```

**312 passed, no skips**, against fresh actual PostgreSQL/pgvector and Redis.
Ruff passed; the exact expanded CI Mypy scope passed 29 source files. The new 35
real-DB settings cases cover scope, inheritance/reset, independent identities,
two-writer create/update conflicts, audit rollback, strict auth/input/constraints
and first-claim/retry freeze. Three additional startup cases reject invalid
enabled model identifiers. Two existing Pydantic deprecation warnings remain.
Migration up/down/up/check passed on a separate newly-created empty database;
no retained/production database was downgraded. CI includes this sequence.

An initial local full run exposed harness omissions: vector was absent from the
new legacy test DB, and inherited CELERY_BROKER_URL overrode the outage test's
REDIS_URL. The new test DB extension was enabled and that environment override
removed only in the test process. The final 312 passed without a product workaround.

Fresh independent read-only adversarial/security review repeated the focused
backend configuration/startup tests, Ruff/Mypy and dashboard tests/typecheck/lint/
audits. It independently reproduced unconfirmed PUT receipt, impossible inherited
source and array-scope acceptance; all now return 502, with regression coverage.
It also caught invalid native HTML pattern and invalid operator-model recovery;
both are fixed and documented in the respective ERRORS files. No open code finding.
The reviewer did not rerun Docker/browser or the full DB suite; it inspects their
saved receipts. Final receipt/documentation review independently compared the
before/after snapshots and inspected both screenshots: APPROVE for commit/push,
no open findings. Exact-SHA CI is checked separately after publication.

## Actual isolated API and browser acceptance

Accepted namespace `nexus-ai-settings-491f4daced734461a823faea29bd5a58` used six
cached-image services on an internal network, no published ports or workers.
The clean AgentHub app source was mounted read-only over the cached image.
Migrations ran only in new test databases. Telegram/LLM credentials and processing
remained disabled; no main rollout or source-image replacement.

Actual AuthFortress/WebHook/AgentHub through the production BFF proved:

- Owner tenant default and bot override persist; reset inherits; another bot
  retains tenant fallback. Stale revision returned409 without extra audit.
- Main scope accumulated five expected audit rows before browser acceptance,
  all attributed to the authenticated owner. No actor came from request JSON.
- Stopping/starting the same Agent retained tenant and bot settings. A tenant
  without bots accepted its own default. Member reads succeeded; BFF and direct
  backend writes were denied. Foreign/inactive scope and revoked sessions failed.
- Job, usage and bot fingerprints and controlled provider counters matched.

Actual Chromium desktop/360 acceptance proved:

- Two owner tabs caused a real 409; the stale editor was cleared until reload.
- Invalid model was blocked locally; warn/error console remained empty.
- During a delayed save, organization/scope/input/Refresh/navigation/logout were
  all disabled; success showed the new revision without enabling processing.
- A 128-character model wrapped at actual 360 px with no horizontal overflow.
- Bot reset inherited the tenant model; a later bot save showed revision 5.
  Bot pages 50 + 2, bot/organization changes, Refresh and section switches cleared
  old editors and unsaved drafts. Empty organization default was saved as revision 2.
- Owned Agent outage caused Save not confirmed, no success/editor/retry. Restoring
  that exact container and reloading showed the unchanged stored state.
- Replacing the session in another tab with a member could not submit the old
  owner form. Reload showed read-only member access; cross-tab logout expired
  the workspace. Viewport reset and all created tabs closed.

![Actual saved bot override](images/dashboard-settings-2026-10-26.png)

Machine-specific ignored commands/receipts retained locally:

```powershell
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/verify_settings_tests_20261026.py
& .venv/tooling-checks/Scripts/python.exe -B .venv/resume_settings_tests_20261026.py
& .venv/tooling-checks/Scripts/python.exe -B .venv/verify_settings_migration_receipt_20261026.py
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/verify_tenant_settings_20261026.py
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/check_settings_preservation_20261026.py
```

## Preservation and limits

Preservation: all **711 baseline container records / 390 volumes / 82 networks**
match exactly. Main SQL schema/rows/sequences, uploads, definitions, environment/
release files, foreign WIP and WSL hashes match. Final **726 containers / 399
volumes / 85 networks**, 50 unchanged images, 70 completed scanners stopped and
only the original nine containers running. No volume/data/container was deleted.

All 15 new containers are stopped: 14 exit 0; the sleep-only test runner exited 137
when stopped, with no OOM. It is not a production acceptance process. The accepted
six-service fixture exited 0. A separate initial API preparation failed because
the private SQL database allowlist omitted its new auth_test membership seed;
all six were retained/stopped 0. This is not counted as accepted verification.
An earlier test-helper type error created only an empty private directory.
The dashboard/bridges closed and port 52233 has no listener.

`003_ai_settings` follows the clean published 002 line. The original AgentHub
checkout's separate `003_tenant_resources` migration is untouched; those lines
require an explicitly reviewed merge before a combined deployment. Nothing was
applied to existing stands. This increment does not verify real model availability,
pricing/quality, Telegram/LLM execution, standalone RAG/cache configuration, public
HTTPS, full scanner smoke or restore-drill. Keys/prompts/activation remain operator-only.
