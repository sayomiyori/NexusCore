# Service Verification Plan

Latest results and remaining blockers: `verification-final-2026-10-04.md`.
Local flows for all five services pass. Full EventPipe lint/public/tenant/durable
delivery gates remain open; the historical checklist below does not override this.

Spec: `../specs/service-verification.md`.

Latest status: **Paused at user request on 2026-10-03**. Current results, blockers,
uncommitted state and resume order: `verification-resume-2026-10-03.md`.
The checklist and evidence below describe the earlier AuthFortress checkpoint;
do not treat them as final five-service acceptance results.

- [x] Locate the five repositories and verify their Git origins and local changes.
- [x] Inspect AuthFortress tests, CI, configuration and auth implementation.
- [x] Capture AuthFortress baseline pytest, Ruff and Mypy results.
- [x] Provision disposable PostgreSQL/Redis and a built AuthFortress HTTP service.
- [x] Remove test database/configuration leaks; run tests against real infrastructure.
- [x] Prove login/JWT/protected endpoint, refresh/replay/logout and failure paths.
- [ ] Prove RBAC, block/revoke behavior, TOTP, OAuth boundary behavior and rate limits.
- [x] Verify migration upgrade/downgrade/model drift and Docker image contents on disposable resources.
- [x] Run a fresh read-only review and security pass; record findings and exact verification commands.
- [ ] Close AuthFortress only when its applicable acceptance gates pass.
- [ ] Repeat the same cycle for WebHook_Manager, AgentHub, EventPipe and PipeWatch in that order.
- [ ] Specify verified cross-service contracts and the first NexusCore E2E scenario.

For each failing behavior: reproduce → regression test → minimal fix → relevant checks → `docs/ERRORS.md` entry in the affected repository. Record blockers without treating mocks or skipped checks as live-provider success.

## AuthFortress checkpoint evidence (2026-10-03)

Final PostgreSQL/Redis pytest run: 41 passed, one upstream TestClient deprecation warning.
Ruff and Mypy passed; HTTP smoke and concurrent refresh checks passed. Reviewer
and Critic reviewed the sensitive fixes independently; the Critic reran the
real PostgreSQL refresh race test and confirmed single-use consumption.

Full AuthFortress verification remains open: provider adapter/failure tests and
live OAuth, remaining 2FA disable/concurrency cases, dependency advisory triage,
and public-deployment configuration. Other services have not been verified in this phase.

Exact commands and results: `../docs/authfortress-checkpoint.md`.
