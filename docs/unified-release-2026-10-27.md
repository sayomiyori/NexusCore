# Unified AgentHub release acceptance — 2026-10-27

AgentHub `11352ffb540893cf3c137a6d424e3fe03a32de0e` combines tenant resource
isolation with the published tenant/bot AI model settings. Both existing 003
revisions retain their definitions; `004_merge_ai_resources` joins their history.
Platform startup rejects either partial head and closes global resource routes.
The original AgentHub checkout and existing databases were not migrated or reset.

## Verification

- The release Dockerfile built successfully and its image ran as UID 10001.
  It contained no `.env`, `.git`, `.venv`, or unguarded HTTP test helpers.
- A fresh internal PostgreSQL/Redis fixture ran **353 tests**, including separate
  empty databases starting from each 003 branch. Synthetic document,
  conversation, usage, settings and audit records survived the merge and the
  merge-marker downgrade/upgrade. `alembic check`, Ruff and scoped Mypy passed.
  The explicit test-only database-creation opt-in was set only for this fixture.
- A fresh six-service fixture exercised the production dashboard BFF and issuer:
  tenant/bot saves, inheritance/reset, stale revision 409, five audit records,
  restart persistence, member/foreign/inactive denials and logout passed. Job,
  usage and bot fingerprints and controlled-provider counters stayed unchanged.
  This was HTTP acceptance; no browser interaction was repeated in this pass.
- The full controlled AI and standalone smoke ran with permanent scanners,
  broker/database outages and numeric-IP callbacks. Both receipts passed and
  record AgentHub `004_merge_ai_resources`; controlled delivery used boundary
  doubles, never actual Telegram or LLM providers. The command was:

```powershell
../WebHook_Manager/.venv/Scripts/python.exe -B scripts/verify_telegram_ai.py --scanners --agent-image nexus-unified-release:20261027-check --agent-revision 004_merge_ai_resources
```

- Root tooling: **133** unittest checks, Ruff and pip check passed. Dashboard:
  **56** tests, typecheck, Biome and production build passed.
- Fresh independent AgentHub code/security review approved after fixes for
  authorization status compatibility, standalone pagination and upload
  ambiguity. A new independent reviewer for the smoke-tool change could not be
  started because the configured model was unavailable; that diff received a
  separate local review and the automated and actual smoke checks above.

The test fixtures used synthetic internal services and cached AuthFortress and
WebHook images. The newly built AgentHub image included all tested runtime code;
the final specification text was revised after the image build without runtime
code changes. Test and smoke receipts remain in the ignored local `.venv`.

## Preservation and limits

The post-run inventory retained all **726** original containers, **399** volumes,
**85** networks and original images. The 70 previously completed scanners remain
stopped. Main database rows/schema/sequences, uploads, deployment definitions and
WSL hashes match the pre-test snapshot. Open WebUI health changed naturally from
`starting` to `healthy`; its remaining container fields match. All 64 new retained
containers are stopped without OOM; the four sleep-only test runners exited 137
when stopped. Successful smoke and BFF fixtures passed their own exit checks.

Earlier fixture attempts are not counted as accepted: one hit Alembic's ambiguous
`downgrade -1`, and another exposed a test using the wrong isolated database.
Both were corrected and rerun. No existing volume or stand data was deleted.
The merge-marker downgrade requires the explicit target
`003_tenant_resources`; downgrading further can remove tenant scope or settings.
Do not apply or stamp this release on an existing database without a separate
reviewed adoption procedure and verified backup.

An unknown document enqueue outcome can leave a document pending; automated
reconciliation is not established. Real lost database acknowledgements and
worker races, public deployment, real provider quality and production load were
not verified by this acceptance.
