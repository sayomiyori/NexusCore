# Isolated portable PostgreSQL restore acceptance

Extend portable-artifact verification with an actual PostgreSQL custom dump,
Windows encryption and Linux decryption/restore. Use only synthetic data in a
fresh UUID-owned PostgreSQL volume. Existing deployment data is read-only for
integrity comparison; no migrations, writes, restarts, WSL changes or providers.

## Acceptance

- Inventory existing containers/volumes/networks/images and protected settings
  before creating resources. Compare every original resource after the drill.
- Resolve cached images to immutable IDs; do not build or pull.
- Create one PostgreSQL container and one standalone Python/cryptography helper,
  both without network access, host ports, restart policy or deployment mounts.
- Use non-root users, dropped capabilities, read-only roots and private tmpfs;
  disable helper logs so decrypted stdout is never stored in Docker logs.
- Validate ownership, names, immutable image, network, mounts and policies before
  starting/stopping owned containers. Preserve all containers and test volume.
- Seed related synthetic rows, binary/Unicode/JSON/null values, schema constraints
  and sequence state. Dump with PostgreSQL 16 `pg_dump --format=custom`.
- Encrypt on Windows with `backup_artifact.py`; send key/token through helper
  stdin only. Run the same committed script on Linux to decrypt. Wrong-key and
  corrupted-token attempts must create no plaintext or successful result.
- Run portable-artifact regressions on Linux. Restore into a different new
  database with `pg_restore --exit-on-error --no-owner --no-privileges`.
- Compare source/restored rows, columns, indexes, constraints and sequence state;
  verify the next generated identity and a rejected foreign-key violation.
- Stop the two owned containers, retain their volume and credential-free receipt.
  Verify the original main database/upload/configuration fingerprints and all
  existing stopped-scanner states remain unchanged.

This proves one bounded local synthetic recovery on two operating systems. It
does not prove off-host storage/access, production restore, coordinated backups,
large-file support, scheduling/retention, RPO or RTO.
