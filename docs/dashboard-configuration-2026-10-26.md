# Read-only AI Configuration acceptance — 2026-10-26

## Implemented

AI Configuration adds an explicit Load configuration action for one active bot
from the existing paged Bots inventory. It displays shared operator-managed
Telegram AI provider, selected/unset model and processing flag. Scope is clearly
platform-wide; this is not a saved bot override or standalone RAG policy. The
flag is not proof of credentials, running workers or provider connectivity.
There are no edit, enable, key, prompt, retry or provider-test controls.

AgentHub adds `/api/v1/tenants/{tenant}/bots/{bot}/ai/configuration` under its
existing opt-in read router. Fresh issuer ai.read and active bot/tenant checks
precede a narrow response projection. No DB session or provider is used. Model
identifiers are bounded and invalid settings fail with a fixed error. Existing
read features remain opt-in; no new variable, dependency, migration or rollout.

The dashboard BFF `/api/configuration` rejects malformed/duplicate/extra scope,
validates Host/session, repeats issuer membership, then checks returned exact
scope/IDs/provider/model/boolean. It reuses bounded private transport and strips
extras. Errors do not become unset settings. Changing bot aborts/clears results;
parent Refresh, tenant, section and bot-page changes reset them.

Backend changes live in `D:/Programming/AgentHub-ai-configuration`, a clean
worktree from verified origin/main. The original AgentHub checkout and its
uncommitted work were not edited or staged. Only the endpoint/schema, new tests,
README and configuration documentation belong to the backend change.
Backend commit: [004f165](https://github.com/sayomiyori/AgentHub/commit/004f165819d7bebd2984a93b08c3bff9bba22ca8).

See [contract](../specs/dashboard-ai-configuration.md) and
[dashboard runbook](../dashboard/README.md).

## Automated checks

From `dashboard/`:

```powershell
$env:NEXT_TELEMETRY_DISABLED='1'
npm test
npm run typecheck
npm run lint
npm run build
npm audit
npm audit --omit=dev
```

**48/48 passed**, including five new BFF HTTP cases for projection, scope/guards,
malformed responses, authorization and source failures. Strict TypeScript,
Biome35, optimized build and both audits passed, **0 vulnerabilities**.

From the AgentHub worktree, with its existing Python environment:

```powershell
python -m pytest tests/test_platform_configuration.py -q
python -m pytest tests/test_platform_configuration.py tests/test_platform_schema.py -q
python -m pytest tests/ -q
python -m ruff check .
python -m mypy app/platform app/api/v1/platform_reads.py
```

New endpoint tests: **24 passed**. Configuration/startup regression: **45 passed**.
Local full discovery: **119 passed / 155 skipped** because isolated DB/Redis test
variables were unset. Full discovery is not claimed as complete DB acceptance.
Ruff passed; Mypy passed12 source files. Two existing Pydantic class-config
deprecation warnings remain outside this scope. A fresh independent read-only
adversarial/security reviewer repeated focused tests, TypeScript/lint/audits and
checked authorization, model validation and stale-response handling without an
open code finding. Exact commit CI is checked separately after push.

The final reviewer also inspected the runtime/browser/preservation receipts,
public documentation and screenshot: APPROVE for commit/push, no open findings.
Docker/browser and production build were run by the builder; the reviewer did
not repeat them. CI remains a separate exact-SHA gate after publication.

## Actual isolated API and browser verification

Accepted namespace `nexus-configuration-36afa82bd2af42c7915e267472c18ece` used six
cached-image services on a new internal network with no published ports/workers.
Only bot and AI read features were enabled. Real Telegram/LLM credentials and
processing remained disabled. Two backend source files were mounted read-only
over the cached image; an owned test factory selected synthetic process settings.
This tests the endpoint, not a rollout of a rebuilt image to the main deployment.

Actual AuthFortress/WebHook/AgentHub through the production BFF verified:

- Null/unset model, then a 128-character synthetic selected model, both with
  processing disabled. Other active bots saw the same explicitly shared policy.
- Foreign tenant denied before Agent access; foreign/inactive bot denied; issuer
  logout invalidated reuse; mutation returned405; resource bridge reads were GET.
- Job/usage/bot fingerprints and controlled provider counters stayed unchanged.

Actual Chromium verified explicit load, 50+2 bot pages, clear on selection/page,
empty/inactive organizations, Refresh and section resets. A delayed old response
did not reappear after changing bots. Stopping only the owned Agent cleared old
settings on Load and showed an unavailable error; restarting that exact container
restored an unset model as Not selected, with processing still disabled. Cross-tab
logout expired the workspace. Captured warn/error console was empty. At360px,
six native tabs wrapped and long model/UUID text had no horizontal overflow.
Temporary viewport reset and created tabs closed.

![Actual synthetic AI Configuration](images/dashboard-configuration-2026-10-26.png)

Private machine-specific commands/receipts, kept ignored:

```powershell
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/verify_configuration_20261026.py
# Production browser acceptance, then owned finish marker.
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/check_configuration_preservation_20261026.py
```

Runtime, browser and preservation receipts passed. Two preparation attempts
were retained: copying into the non-root image was denied; the next private
ownership guard did not normalize Docker Desktop's Windows/Linux mount paths.
Read-only exact source mounts and a normalized guard fixed the harness; no app
permission or security constraint was weakened. Those attempts were not counted
as acceptance. All18 owned containers are stopped with exit0/noOOM; their data
and volumes remain. Host dashboard/bridges closed.

## Preservation and remaining scope

All **693 baseline containers / 381 volumes / 79 networks** match exactly.
Main SQL schema/rows/sequences, uploads, definitions, root environment/release,
protected files and WSL hashes match. Final **711 containers / 390 volumes /
82 networks**, 50 unchanged images,70 completed scanners stopped and only the
original nine containers running. Foreign root README/hardening WIP preserved.

Not verified here: durable tenant/bot overrides or editing, standalone RAG
configuration, actual execution, credentials/provider readiness, public HTTPS,
full scanner smoke or restore-drill. Owner was used in the real browser/issuer;
member access and malformed authorization are covered by HTTP boundary tests.
