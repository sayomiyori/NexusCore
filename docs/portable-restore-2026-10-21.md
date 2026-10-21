# Portable restore and artifact verification acceptance — 2026-10-21

Root tooling revision `7717d6d` passed a fresh isolated synthetic PostgreSQL
dump/restore drill after the [full scanner smoke](isolated-smoke.md#full-scannerload-acceptance-after-cli-changes-on-2026-10-21).
This verifies the new `backup_artifact.py verify` command from `2ee553c` on
Windows and Linux, alongside actual decryption and restore. It follows the
[existing acceptance contract](../specs/portable-restore-drill.md).

## Owned resources

Project: `nexus-backup-ab7fce3f4ee3438a9c762300542574bb`.

| Resource | Immutable ID / name |
| --- | --- |
| PostgreSQL image | `sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b` |
| Linux helper image | `sha256:7cae10258f593cf22149130b306181ce26fa910542b96dc60582be9c333634d4` |
| PostgreSQL container | `a6fef46382a78d6abfb58504fa5aec0769f02ce580197e6ff0de3e244d8aba00` |
| Linux helper container | `afce49605abcac7544e36003bf6deaf3e85aa2baf196935a2899269bd80dbb22` |
| Retained volume | `nexus-backup-ab7fce3f4ee3438a9c762300542574bb-data` |

Both containers used network `none`, no published ports, restart `no`, read-only
roots, dropped capabilities, `no-new-privileges`, private tmpfs and 256 MiB
memory/swap limits. PostgreSQL ran as `postgres`; the standalone Python helper
ran as UID/GID `10001:10001`. Both log drivers were `none`. Only the new UUID
volume was mounted; no image was built/pulled and no network was created.

Ownership, immutable images, definitions, mounts and policies were checked
before lifecycle operations and SQL. The existing exact-hash proof accepted
only Docker's `OomKillDisable=false` to `null` representation change. No old
fixture was resumed. Database password values used inherited environment;
key/token values used helper stdin, never command arguments or logs. Synthetic
artifacts remain private under ignored `.venv`; parent directories must be
trusted and Windows ACLs remain the operator's responsibility.

## Verification

The private driver was `.venv/portable_restore_drill_20261021.py`. `PG` and
`CRYPTO` below denote the exact owned IDs above; `DIR` is the private project
directory. Binary transfer used subprocess argument arrays and captured byte
stdin/stdout, not PowerShell text pipelines.

```text
../WebHook_Manager/.venv/Scripts/python.exe -B .venv/portable_restore_drill_20261021.py
docker exec PG pg_dump -U drill -d fixture_source --format=custom
python -B scripts/backup_artifact.py keygen --output DIR/recovery.backup-key
python -B scripts/backup_artifact.py encrypt DIR/synthetic.dump --key-file DIR/recovery.backup-key --output DIR/synthetic.fernet
python -B scripts/backup_artifact.py verify DIR/synthetic.fernet --key-file DIR/recovery.backup-key
docker exec --workdir /tmp/portable-drill CRYPTO python -B -m unittest discover -s tests -p test_verify_backup_artifact.py -v
python -B /tmp/portable-drill/scripts/backup_artifact.py verify /tmp/portable-drill/recovery.fernet --key-file /tmp/portable-drill/recovery.backup-key
python -B /tmp/portable-drill/scripts/backup_artifact.py decrypt /tmp/portable-drill/recovery.fernet --key-file /tmp/portable-drill/recovery.backup-key --output /tmp/portable-drill/restored.dump
docker exec -i PG pg_restore -U drill -d fixture_restored --exit-on-error --no-owner --no-privileges
docker stop --time 15 PG
docker stop --time 15 CRYPTO
```

The Linux verify/decrypt commands ran inside `CRYPTO`. The same current
`backup_artifact.py` and `local_files.py` were transferred with the regression
tests through `docker exec -i ... python -B -c` and stdin JSON. Before execution,
review caught an escaped-newline error in the prepared private helper; converting
the embedded code to a raw string fixed it, and both embedded programs compiled.
No restore-drill container had been started when that preparation error was found.

| Check | Result |
| --- | --- |
| Driver | Exit 0; receipt `passed=true`, phase `complete` |
| Dump | 4,463 bytes; PostgreSQL custom format `PGDMP` |
| Dump SHA-256 | `35dc0ecda413e666d72c09d47931b85b406ff0e7c68a36aa72028fffe227b2d9` |
| Transferred backup source SHA-256 | `91988882e245b85cb09ba529179f4bd163c9e5bb87650b94f861499f6cff8510` |
| Transferred file helper source SHA-256 | `99abae4e27f1558b1353251c0c80e71b6027873713b6e7b4f6527f9f23601f89` |
| Windows verify | Authenticated successfully; directory/file hashes unchanged |
| Linux verify | Valid token accepted; wrong key/tamper rejected with static diagnostics; directory/file bytes unchanged |
| Linux decrypt | Wrong key/tamper created no plaintext; valid bytes exactly matched the Windows dump |
| Linux regressions | 19 discovered: 17 passed, two Windows-only handle tests skipped |
| Source/restore | Two tenants, three related events; Unicode/null/JSON/binary fields equal |
| Schema | Columns, identity metadata, indexes, constraints and view results equal |
| Sequence | `last_value=41`, `is_called=true`; next generated identity `42` |
| Negative SQL | Transactional invalid-tenant insert rejected with SQLSTATE `23503` |
| Cleanup | Both owned containers stopped, exit 0, no OOM, restart `no`; volume retained |

The restore snapshots preserved all 524 pre-drill containers, 269 volumes,
networks/images/protected files and 70 completed scanner states. Comparing
against the earlier pre-smoke baseline also preserved all 501 original
containers, 263 volumes and 65 scanner states. Final inventory: 526 containers,
270 volumes, 70 stopped scanners; only the original nine containers running.
The old dead container remained unchanged; inventory used `--size=false` and
[bounded inspect batches](ERRORS.md#2026-10-21-private-inventory-exceeded-the-windows-process-argument-limit).

Main PostgreSQL rows/schema/sequences/metadata, uploads/content/modes, nine
container definitions and `.env`/release/WSL hashes matched before smoke,
after smoke and after restore. The integrity command was:

```powershell
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/capture_stack_smoke_root.py .venv/post-tooling-smoke-20261021-main-before.json
```

Root checks passed with 92 tests, Ruff and compilation:

```powershell
& .venv/tooling-checks/Scripts/python.exe -B -m unittest discover -s tests -p 'test_verify*.py' -q
& .venv/tooling-checks/Scripts/python.exe -B -m ruff check --no-cache scripts tests
& .venv/tooling-checks/Scripts/python.exe -m compileall -q scripts tests
```

Independent read-only/security review inspected the current scripts, receipts,
source hashes, original-resource comparisons and stopped-container policies.
No product source, dependency or deployment configuration fix was needed.

## Limits

This is one local synthetic restore across Windows and a Linux container sharing
the same machine. Off-host access/storage, production or coordinated whole-stack
restore, large-file support, scheduling/retention and RPO/RTO remain unverified.
Docker Desktop was not restarted; WSL settings and deployment data were not
changed. Real Telegram/LLM services were not enabled.
