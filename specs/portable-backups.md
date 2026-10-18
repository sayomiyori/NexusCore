# Portable backup artifacts

The existing local recovery copies use Windows user-bound DPAPI. Add portable
authenticated encryption for existing small dump/archive files so an operator
can carry a backup and its separately stored key to a different host.
Use the already installed `cryptography` Fernet implementation; no custom cipher,
password derivation, database connection or archive extraction.

## Contract

`scripts/backup_artifact.py keygen --output PATH` creates a random 44-byte key.
`encrypt SOURCE --key-file PATH --output PATH` creates a standard Fernet token.
`decrypt SOURCE --key-file PATH --output PATH` authenticates before creating any
plaintext output. The key is read from a file, never an argument value or stdout.
All outputs use exclusive creation and mode 0600 where supported. Parent
directories must already exist and be trusted; Windows access follows their ACLs.
Existing files, directories and final-component symlinks are never overwritten.
Inputs must be regular files; plaintext is capped at 16 MiB, ciphertext at 24 MiB.
Fernet operates in memory; large production archives need a streaming backup tool.

Missing/malformed keys, wrong keys, corruption, oversized/nonregular input and
I/O errors fail with static diagnostics and exit 1. Invalid CLI syntax exits 2.
Never echo key material, paths, data or exception details. Failed authentication
creates no output. An I/O failure can leave an incomplete newly created file;
exit 1 makes it unusable and existing files remain intact. Do not automatically
delete input/output files or read `.env`. Losing the key makes recovery impossible.
The Fernet timestamp is public; encrypted content/filenames are not a manifest.

## Acceptance

- Real CLI roundtrip in separate processes, including binary/empty input.
- Wrong key, malformed/tampered/truncated token: no plaintext output or disclosure.
- Missing/oversized key/input, unsafe file types and occupied output fail safely.
- A file created just before output creation is preserved.
- Root regressions, Ruff, compilation and fresh security/read-only review pass.
- Follow with a retained, isolated PostgreSQL dump/restore drill. Off-host storage,
  scheduling, whole-stack recovery and real deployment data remain separate.
