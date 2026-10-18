# Portable encrypted PostgreSQL restore acceptance — 2026-10-19

## Verified boundary

Windows encrypted a real PostgreSQL 16 custom dump with the committed
`scripts/backup_artifact.py` from `9fe46da`. A Linux Python helper ran the same
script to decrypt it; PostgreSQL restored the resulting bytes into a different
new database. All data was synthetic. This closes a local cross-platform
artifact/restore rehearsal, not off-host or production recovery.

The drill followed [the acceptance contract](../specs/portable-restore-drill.md).
No dependency, deployment configuration, main database, existing container or
WSL setting was changed. No real Telegram/LLM service ran.

## Fixture and safety

Successful project: `nexus-backup-e6d5c914f8fb4492978e0e0a7149a476`.

| Resource | Immutable ID / name |
| --- | --- |
| PostgreSQL image | `sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b` |
| Linux crypto image | `sha256:7cae10258f593cf22149130b306181ce26fa910542b96dc60582be9c333634d4` |
| PostgreSQL container | `8f7141eb67711b44d1084e47d61504e12530fbcf5963c1fa924e46a88fa67697` |
| Linux crypto container | `95d1c3485eb00d33a7f103e4df8154c2c02af9f9f065eaff6b9a158a01f53da0` |
| Retained data volume | `nexus-backup-e6d5c914f8fb4492978e0e0a7149a476-data` |

Both containers used `--network none`, no published ports, `--restart no`,
read-only roots, dropped capabilities, `no-new-privileges`, a 256 MiB memory
limit and private tmpfs. PostgreSQL ran as `postgres`; the crypto helper ran as
UID/GID `10001:10001`. Its entrypoint was standalone Python, never the cached
image's application. Both log drivers were `none`; decrypted binary stdout
was captured in memory, not Docker logs. Only the new PostgreSQL volume was
mounted. No image was built or pulled; no new Docker network was created.

The random test database password was passed through inherited environment,
never a command argument value. The portable key and token reached Linux via
stdin, never command arguments or container environment. Host artifacts stayed
inside ignored `.venv`; the test key was not committed. Parent directories were
operator-controlled; Windows ACLs remain the operator's responsibility.

Before start/stop/SQL, the private driver checked exact owned IDs/names/labels,
images, mounts and policies. Docker changed `HostConfig.OomKillDisable` from
`false` at creation to `null` after start. The comparator accepted that change
only when replacing this one actual `null` with `false` reconstructed the exact
original Config/HostConfig/mounts hash. A true disabled-OOM policy was not an
allowed normalization. Explicit CLI `--oom-kill-disable=false` did not prevent
the representation change.

## Commands and results

The private synthetic driver was `.venv/portable_restore_drill_20261019.py`;
captured command output/errors were withheld by default. The actual operations
below were issued as subprocess argument arrays, with binary stdin/stdout, not
PowerShell text pipelines. `PG` and `CRYPTO` denote the exact owned IDs above;
`DIR` denotes the project's ignored private directory.

```text
docker exec -i PG psql -X -q -A -t --set ON_ERROR_STOP=1 -U drill -d fixture_source
docker exec PG pg_dump -U drill -d fixture_source --format=custom
python -B scripts/backup_artifact.py keygen --output DIR/recovery.backup-key
python -B scripts/backup_artifact.py encrypt DIR/synthetic.dump --key-file DIR/recovery.backup-key --output DIR/synthetic.fernet
docker exec --workdir /tmp/portable-drill CRYPTO python -B -m unittest discover -s tests -p test_verify_backup_artifact.py -v
python -B /tmp/portable-drill/scripts/backup_artifact.py decrypt /tmp/portable-drill/recovery.fernet --key-file /tmp/portable-drill/recovery.backup-key --output /tmp/portable-drill/restored.dump
docker exec -i PG pg_restore -U drill -d fixture_restored --exit-on-error --no-owner --no-privileges
docker stop --time 15 PG
docker stop --time 15 CRYPTO
```

The Linux decrypt command ran as a subprocess inside `CRYPTO`; setup and
transmission used `docker exec -i ... python -B -c` with a fixed bootstrap and
stdin JSON. It first rejected a random wrong key and a modified token, with no
plaintext output, then decrypted the valid token. The returned bytes exactly
matched the Windows source dump before they reached `pg_restore`.

| Check | Result |
| --- | --- |
| Dump | 4,463 bytes; PostgreSQL custom format (`PGDMP`) |
| Dump SHA-256 | `b66965211b2a7e8edede56f172b81473991e45a263f735c285a501218080064f` |
| Script SHA-256 (Windows and Linux) | `39eed88c22cf488bc19963fac6425acb9a2526484bac694ab07d98d91eedc861` |
| Linux artifact regressions | 10 passed, no skips |
| Source/restore | Two tenants, three related events; Unicode, null, JSON and binary fields equal |
| Schema comparison | Columns, identity metadata, indexes, constraints and view results equal |
| Sequence | Restored `last_value=41`, `is_called=true`; next generated identity `42` |
| Negative SQL | Insert with unknown tenant rejected with foreign-key SQLSTATE `23503` |
| Final successful containers | Both stopped, exit 0, no OOM, restart policy `no` |

An initial fingerprint query attempted to serialize a sequence relation as a
composite row and failed with SQLSTATE `42809`. It was corrected to explicitly
read `last_value` and `is_called`; no source data was changed by that failed
read. The successful comparison covered these values before the next-ID probe.
The foreign-key rejection was independently repeated in a transaction with
`psql` SQLSTATE-only verbosity; `.venv/portable_restore_negative_20261019.py`
confirmed `23503`, then stopped only the owned PostgreSQL container, exit 0.

## Preservation and retained attempts

Strict definition checks stopped two earlier setup attempts on the OOM-field
representation change before synthetic seeding. Their resources remain:

- `nexus-backup-2d5af05620044ba6af1540408087b868`: two stopped containers and one volume.
- `nexus-backup-29d988dad3f4466f98bbf057a7228b0e`: one stopped PostgreSQL container and one volume.

All three owned PostgreSQL containers exited 0. The first discarded Python
sleep helper required Docker's stop timeout and exited 137, without OOM. The
successful helper installed a SIGTERM handler and exited 0. Nothing was deleted.

The final comparison against the inventory from before the first attempt
preserved all **404 original containers, 236 volumes, networks, cached images,
protected configuration hashes and all 45 completed scanner states**. Five owned
containers and three owned volumes were retained across the attempts, giving
409 containers and 239 volumes. Only the original nine containers were running.
The unrelated historical dead container was unchanged.

Main PostgreSQL rows/schema/sequences/metadata, uploads/content/modes, all nine
main container definitions, `.env`, release override/state hashes and
`.wslconfig` hashes matched the before snapshot. Commands:

```powershell
../WebHook_Manager/.venv/Scripts/python.exe -B .venv/capture_stack_smoke_root.py .venv/portable-backup-20261019-main-before.json
../WebHook_Manager/.venv/Scripts/python.exe -B .venv/portable_restore_negative_20261019.py
docker ps --all --size=false --format '{{json .}}'
```

The integrity command ran before and after the drill: baseline captured, then
`PASS` unchanged. The JSON inventory was captured and parsed privately; raw
command/label fields were not printed. Receipts contain fingerprints and owned
IDs, not keys, passwords, dump contents or original database rows.

Root verification for the feature: 53 tests passed in 23.579 seconds, Ruff and
compilation passed. Independent security review approved after the Windows
dangling-link and CLI diagnostic fixes. GitHub Actions run
[39172720921](https://github.com/sayomiyori/NexusCore/actions/runs/39172720921)
passed on both Ubuntu and Windows for `9fe46da`.

## Still unverified

The Linux helper shares this machine's Docker engine; this is not a second-host
recovery. There was no off-host upload/access test, real deployment restore,
large-file/streaming test, coordinated database/upload recovery, backup schedule,
retention policy, RPO/RTO measurement or new production activation. Retained
fixture volumes are local test data, not backups of the deployment.
