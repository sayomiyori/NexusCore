# Coordination Hub repository-qualified reservations and review (candidate)

Status: candidate patch, uncommitted, in `D:/Programming/NexusCore/.worktrees/development` on branch `agent/development`. The running Hub, the live database and the global OpenCode profiles are unchanged.

## Why

The Hub store already namespaced leases and review evidence by repository, but the MCP and identity layers did not: `lock_files` and `get_file_owners` had no `repository` parameter, `submit_for_review` hardcoded the NexusCore worktree, and `verify_revision` rejected every repository except `nexuscore`. A second repository could therefore not be reserved or reviewed even though the schema supported it.

## Provenance

Baseline copied byte for byte from the read-only foreign implementation at `D:/Programming/NexusCore/.worktrees/coordination-hub` (detached `ba2ca02`, all files untracked). The foreign worktree was not modified.

| Baseline file | sha256[0:16] |
|---|---|
| `coordination_hub/backup.py` | `d65d7bf0d9f842eb` |
| `coordination_hub/backup_runner.py` | `46785dcbaf043fbb` |
| `coordination_hub/directory_guard.py` | `a075d55a855d0e50` |
| `coordination_hub/identity.py` | `430968ccf2e504c2` (modified here) |
| `coordination_hub/paths.py` | `8cb53d3d33290015` |
| `coordination_hub/persistent.py` | `6be89258e4403696` |
| `coordination_hub/requirements.txt` | `2be59ec00f23de78` |
| `coordination_hub/server.py` | `a2bc0efd773883c0` (modified here) |
| `coordination_hub/SPEC.md` | `3ed5b8895f0610c0` (modified here) |
| `coordination_hub/store.py` | `cb72f863883322cf` (unchanged) |
| `coordination_hub/test_access.py` | `0110a000ece3f083` |
| `tests/coordination/test_access.py` | `2e04ffe1dd0ecb6c` |
| `tests/coordination/test_backup.py` | `91a766202eb40417` |
| `tests/coordination/test_contract.py` | `3f93aee94b558469` |
| `tests/coordination/test_directory_guard.py` | `5d5e8074b4110bf0` |
| `tests/coordination/test_identity.py` | `fefc71b6596e1ac9` (modified here) |
| `tests/coordination/test_mcp.py` | `6f01228613221218` (modified here) |
| `tests/coordination/test_paths.py` | `42bf2353e0eaf3ff` |
| `tests/coordination/test_persistent.py` | `b2bd20172c7c4ac6` |

## Change

`identity.py`

- Adds `REPOSITORY_ROOTS` with exactly two allowlisted roots: `nexuscore` at `D:/Programming/NexusCore` and `authfortress` at `D:/Programming/AuthFortress`. No caller-supplied root is accepted.
- Adds `repository_root()` and `worktree_for()`. The only accepted worktree is `<root>/.worktrees/<agent>` on `refs/heads/agent/<agent>`.
- `verify_worktree()` now checks the repository, rejects a root that is not that repository's fixed root, and keeps rejecting the main checkout, foreign paths, unregistered worktrees, wrong or detached branches, links, reparse points and hard links. It validates the configured path as stored before resolving it, and matches other agents' registry entries by name only so a stale entry cannot abort the caller.
- `verify_revision()` rejects a repository that is not allowlisted and verifies the worktree of the submitted repository.
- Adds `verify_submission()` (the submitting agent's own worktree in the submitted repository) and `verify_reservation_scope()` (the reserving agent's own worktree). A missing worktree of a *different* agent is tolerated, so one agent's incomplete registration never blocks another agent's lease.

`server.py`

- `lock_files(..., repository='nexuscore', ...)` and `get_file_owners(paths, repository='nexuscore')`. Defaults keep the existing client contract.
- Unknown repository ids are rejected before any database work.
- The reservation preflight verifies the caller's own worktree for the requested repository, then checks every existing target path for links and reparse points across that repository's agent worktrees.
- A default-repository reservation keeps the original canonical request payload (`task_id`, `paths`, `ttl`), so request IDs persisted by the previous Hub still replay; `repository` is only part of the payload when it is not `nexuscore`.
- The submission preflight is `verify_submission(identity, repository, revision)`.
- The repeated hardcoded `D:/Programming/NexusCore` root argument is replaced by `repository_root('nexuscore')`, so a test can inject disposable roots through `runpy` while production still reads the same fixed allowlist constant.

`SPEC.md` records the repository-qualified contract and the fail-closed conditions.

`store.py` is byte-identical to the baseline: the schema already namespaces leases and reports by repository, so **no migration and no schema write** is needed. The live database was read with `mode=ro` and reported `application_id 1314419522`, `user_version 4`, `leases(repository, path, task_id, owner, lease_id, expires_at)`, `reports(..., repository, revision, ...)`.

## Evidence

Run from the development worktree root:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"
python -B -m unittest discover -s tests/coordination -p "test_*.py"
# Ran 61 tests ... OK   (zero skips)
D:/Programming/NexusCore/.venv/tooling-checks/Scripts/python.exe -m ruff check coordination_hub tests/coordination
# All checks passed!
```

Every identity, repository-scope and full-stdio test uses disposable Git repositories created in a
temporary directory, with the repository roots injected into the server through
`runpy`: the wrapper patches `identity.REPOSITORY_ROOTS` and then runs the real
`server.py`, so the production allowlist stays fixed and nothing is
environment-configurable. Three startup and rejection tests
(`test_provisioned_live_database_starts`,
`test_live_database_missing_does_not_get_created`,
`test_rejects_wrong_worktree_before_database_creation`) still pass the literal
real NexusCore paths, which is the intended fixed-root behaviour of a local
pilot; none of them requires a worktree to be clean. The suite therefore stays
green while the AuthFortress security worktree is legitimately dirty.

`test_repository_scope.py` builds its own repository with `agent/security`,
`agent/codex` and a deliberately mis-branched `agent/development` worktree, and asserts both directions: the correct worktree, branch and clean HEAD pass; a wrong revision, a dirty tree, a missing worktree, a wrong branch, the main checkout, a foreign path, an unlisted repository and a linked path all fail closed. It also covers a stale registration of another agent and a symlinked configured root.

`test_stdio_task_flow` runs the complete tool flow with no skips and no conditional assertions: `codex` plus `development` exercise claim, heartbeat, status, default-repository lease and renewal in a temporary database, then `security` reserves `app/main.py` in the injected `authfortress` repository, the same path stays invisible in the `nexuscore` namespace, and `security` submits that repository's worktree HEAD for review, which `codex` completes.

Manual acceptance, also fully disposable:

```powershell
python -B tests/coordination/manual_repository_acceptance.py
# 11/11 checks passed
```

It proves the end-to-end path that the baseline could not: `security` reserves `app/main.py` in `authfortress`, the lease is invisible from the `nexuscore` namespace, `development` is refused because it has no AuthFortress worktree in the fixture, `security` submits AuthFortress evidence and `codex` completes the review, while a wrong revision and an unconfigured repository are rejected.

## Review fixes

Three review blockers were fixed with a regression each. Every regression was run against a temporary copy of the pre-fix code and fails there, so none of them passes vacuously.

1. **Legacy request replay.** A default-repository `lock_files` request now keeps the pre-repository canonical payload `{task_id, paths, ttl}`; `repository` is only added when it is not `nexuscore`. A UUID persisted by the previous Hub therefore replays to its stored result instead of raising `Request ID already used`. Regression: `test_legacy_request_id_replays_to_stored_result`, which seeds a request row with the old fingerprint.
2. **Stale registered worktree of another agent.** `verify_worktree` matches registry entries by normalized name and resolves only the caller's own path, so a missing or renamed worktree of an unrelated agent no longer aborts a valid caller. Regression: `test_stale_registered_worktree_of_another_agent_does_not_block`.
3. **Symlinked configured root.** The configured path is checked component by component for links and reparse points *before* any resolve, so a symlinked or junctioned repository root cannot be followed into a correctly registered repository. Regression: `test_configured_root_symlink_is_rejected`.

Untouched by this candidate, verified after every run: the foreign `coordination-hub` worktree (still detached, still untracked, no new files), the live `D:/NexusCoreCoordination/hub.sqlite3` (schema read only) and the AuthFortress main checkout (five modified files and untracked `.serena` preserved). The AuthFortress worktrees are not modified here either; the security worktree now carries the security task's own uncommitted fixes.

## Final review evidence

Exact commands and results for the last review round, run from the development worktree:

```powershell
D:/Programming/NexusCore/.venv/tooling-checks/Scripts/python.exe -m ruff check coordination_hub tests/coordination
# All checks passed!

python -B -m unittest discover -s tests/coordination -p "test_*.py"
# Ran 61 tests in 52.6s
# OK   (zero skips)

python -B tests/coordination/manual_repository_acceptance.py
# 11/11 checks passed

git diff --check
# no whitespace errors
```

Notable review fixes in this candidate, in the order they were found:

- Three P2 blockers from independent review, each with a discriminating regression: the legacy default-repository request fingerprint, a stale registered worktree of another agent aborting a valid caller, and a symlinked configured root accepted after resolve.
- Test hygiene: the full stdio flow and the identity/repository-scope tests moved to injected disposable Git repositories, so a legitimately dirty AuthFortress worktree cannot break or skip them; the three startup/rejection tests keep their literal fixed-root paths by design.
- Six Ruff findings in the new paths fixed with no unrelated reformatting.
- Cross-service 2FA contract recorded in `specs/auth-session-hardening.md`, accepted against `AuthFortress/docs/ERRORS.md` entry `2026-11-01`.

### AuthFortress isolated review

Run by the AuthFortress security work, not by this candidate, in
`D:/Programming/AuthFortress/.worktrees/security` with the AuthFortress
interpreter `D:/Programming/AuthFortress/.venv/Scripts/python.exe`:

```powershell
D:/Programming/AuthFortress/.venv/Scripts/python.exe -B -m pytest -q --tb=short
# 231 passed in 54.63 s, audit 0

D:/Programming/AuthFortress/.venv/Scripts/python.exe -B -m ruff check --no-cache app tests scripts
# no findings

D:/Programming/AuthFortress/.venv/Scripts/python.exe -B -m mypy --no-incremental app
# 39 files checked, no issues

git diff --check
# clean
```

Two narrow reruns used the same interpreter and working tree: the pair-specific
backup-code rollback and auth-audit tests reported 2 passed, and the post-full
audit-only rerun reported 1 passed with audit 0.

Environment: a fresh database owned by this task, with
`DATABASE_URL == TEST_DATABASE_URL` so a misdirected run cannot reach another
database, and a task-owned Redis fixture on `TEST_REDIS_URL` using database 15
only. No production credentials or shared services were used.

Scope of the approval: limited to these local isolated runs, plus 21 synthetic
HTTP edge controls. It does not cover live OAuth provider round trips, production
deployment, load or performance testing, or a full dependency audit.

No commit, push or deployment was performed; the candidate is uncommitted in `D:/Programming/NexusCore/.worktrees/development` on `agent/development`.

## Live wiring

Live coordination does not use a profile file. The coordinator starts `security`
with a task-local inline runtime configuration derived from the secret-free
candidate profile, with only the database argument changed to the existing
`D:/NexusCoreCoordination/hub.sqlite3`. No global profile is edited, no running
client is repointed or stopped, and the schema already matches, so there is no
migration.

The coordinator independently read the live candidate under the `codex` identity:
`get_file_owners(repository='authfortress')` returned its active paths,
`get_task` reported `owner=security`, and no mutation occurred. That read-only
check resolved the earlier live-wiring limitation; the remaining acceptance for
AuthFortress leases belongs to the security task, not to this candidate.

`coordination_hub/profiles/opencode-security-candidate.json` stays a
development-only smoke artifact pointing at a temporary database. It is not the
live wiring, and no live-pointing profile was created.

## Boundaries

- Hub still verifies the configured worktree and branch, not a client's real working directory; reservations remain advisory.
- The AuthFortress worktrees were registered by the coordinator from `main@116ffdb8`. The original dirty main checkout is preserved and still visible: its five modified files and untracked `.serena` remain. Only the new `/.worktrees/` directory is excluded locally through `.git/info/exclude`; no tracked ignore file was edited.
- Repository ids without a configured worktree (`webhook_manager`, `agenthub`, `eventpipe`, `pipewatch`) stay in the lease namespace for compatibility but can never produce review evidence.
- No role-to-repository restriction was added; the review evidence records the repository and revision per submission.
