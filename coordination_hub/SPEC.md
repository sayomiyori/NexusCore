# Coordination Hub local operation

Status: local trusted-agent pilot. This is not a security boundary between processes of the same Windows user. A process can impersonate another agent and the account owner can change SQLite and audit data. File leases are advisory and do not prevent direct edits. The server verifies the configured worktree and branch, not the client's actual working directory.

The stdio server shares `D:/NexusCoreCoordination/hub.sqlite3` between security, development and codex. It verifies its fixed worktree mapping and opens the existing database fail-closed. The database directory has an explicit owner/SYSTEM/Administrators ACL and is pinned against rename for each server process. SQLite connections and path checks do not protect against a malicious process using the same Windows account. Git status and HEAD checks are not atomic with later worktree changes.

Claim tasks before work, reserve all affected paths, renew active leases, report status and communicate conflicts. Codex reviews the submitted repository and full commit ID; the server requires a clean worktree of that repository at that HEAD. A matching report does not prove that review was actually performed. Mutations take UUID request IDs; reusing an ID with different arguments fails. A repeated expired or released lease result is rejected rather than presented as current ownership. Reservation conflicts include parent and child paths. Heartbeat and lease renewal require explicit calls; they are not automatic.

Hub runs fixed read-only Git commands; it does not commit, merge, push, run arbitrary commands, manage Docker, or edit repository files. Events are append-only through the application, but are not tamper-proof.

## Repositories and worktrees

Two repository ids are configured for MCP use: `nexuscore` (`D:/Programming/NexusCore`) and `authfortress` (`D:/Programming/AuthFortress`). The store still namespaces leases for six repositories, but only a configured repository can produce verified review evidence.

Reservations and review are repository-qualified. `lock_files` and `get_file_owners` take `repository` and default to `nexuscore`; `lock_files` requires the calling agent's own worktree in that repository. `submit_for_review` verifies the calling agent's worktree of the *submitted* repository. The accepted location is fixed by convention, `<root>/.worktrees/<agent>` on branch `refs/heads/agent/<agent>`; the main checkout, a foreign path, an unregistered worktree, another branch, a linked or reparse-point path, a dirty tree or a revision other than `HEAD` all fail closed. A repository whose worktree does not exist yet is unusable for that agent, and the absence of another agent's worktree never blocks the calling agent's lease. Hub never creates a worktree of another repository.

Repository worktrees for AuthFortress were registered from `main@116ffdb8`. The original dirty AuthFortress main checkout is preserved and still visible; only the new `.worktrees/` directory is excluded locally through `.git/info/exclude`, not a tracked ignore file.

## Task-local configuration

`coordination_hub/profile_tool.py` prints the OpenCode `mcp.servers.nexus_hub` entry to stdout and nothing else:

```text
python -B coordination_hub/profile_tool.py --agent security [--database <hub.sqlite3>]
```

The agent must be `security` or `development`; the reviewer role does not reserve work. `--database` defaults to the live Hub database and accepts only paths the server already accepts: the live Hub database, a `hub.sqlite3` inside the temporary directory, or the synthetic connectivity database. The tool rejects links and reparse points on that path, requires an existing regular file, and validates it with the store's own schema check over a read-only SQLite URI, so a database carrying the expected application id and version but unrelated tables or triggers is refused. It also requires the emitted interpreter and server entry point to exist, and reuses the fixed worktree and branch verification. Diagnostics are static, so a failure never echoes arguments, environment values or database content.

These are preflight checks. The server re-reads the same state when it starts, so a later change of database, worktree or branch is not prevented by the emission.

The tool writes no file and edits no profile; a caller stores or injects the output itself, so it cannot change a running client or a global configuration.


## Backups and recovery

Windows task `NexusCore Coordination Hub Backup` runs daily at 03:00 when the user is logged on; missed runs use StartWhenAvailable. It saves verified SQLite Backup API snapshots in `D:/NexusCoreCoordinationBackups`, retaining up to 30 complete snapshot/hash pairs. Both directories are on D:, so this does not protect against loss of the disk. The backup directory is dedicated to Hub: all valid `backup-<UUID>.sqlite3` / `.sha256` pairs may be rotated by Hub. Other files must not be placed there with those names. A share-exclusive lock prevents concurrent backup processes; failure is recorded in `backup-status.txt` and in Task Scheduler LastTaskResult. There is currently no automatic notification.

After interrupted publication or rotation, mismatched snapshots, markers or staging files stop backups without removing files. Inspect Task Scheduler and the status file. Stop all Hub clients, preserve the current database and backup directory, and inspect each snapshot with SQLite `PRAGMA integrity_check` and its SHA-256 before deciding how to resolve the incomplete pair. Do not delete, overwrite, or restore automatically. To recover, first restore a selected snapshot to a separate new file using SQLite Backup API and validate integrity and schema. Stop all clients before any replacement of the working database, preserve the previous database and sidecars, then reconcile tasks, leases and pending requests: a snapshot does not contain operations performed after it was taken, so old request IDs must not be automatically replayed as exactly-once operations.

## Boundaries

The server and scheduler currently run code from an uncommitted detached worktree at `D:/Programming/NexusCore/.worktrees/coordination-hub`; removing that worktree or changing its Python runtime breaks both. Current OpenCode sessions were connected dynamically. Standalone new sessions can load `D:/NexusCoreCoordination/opencode-security.json` or `opencode-development.json` using `OPENCODE_CONFIG`; matching `start-*.ps1` launchers select the assigned worktree. Fresh standalone `opencode run` calls accessed the Hub with both profiles, even though `opencode mcp list` printed an empty list. Codex was registered globally and a fresh read-only Codex CLI session successfully read its inbox; this does not prove an already-running Desktop chat loaded the new server. Test results do not establish a real development/review/merge cycle. Do not include credentials or production secrets in tasks, messages or reports.
