# Portable encrypted backup artifacts

Existing Windows DPAPI copies remain user-bound local recovery copies. For a
small existing PostgreSQL custom dump or archive, this tool creates a portable
[Fernet authenticated token](https://cryptography.io/en/latest/fernet/) using the
already pinned `cryptography` dependency. It never connects to a database, reads
`.env`, extracts archives or deletes files. It does not convert DPAPI copies.

Use an existing private directory. On Windows restrict its ACL to the operator;
POSIX output creation requests mode 0600. Parent directories must be trusted.

```powershell
.venv/checks/Scripts/python.exe scripts/backup_artifact.py keygen --output .venv/recovery.backup-key
.venv/checks/Scripts/python.exe scripts/backup_artifact.py encrypt .venv/synthetic.dump --key-file .venv/recovery.backup-key --output .venv/synthetic.dump.fernet
.venv/checks/Scripts/python.exe scripts/backup_artifact.py decrypt .venv/synthetic.dump.fernet --key-file .venv/recovery.backup-key --output .venv/restored.dump
```

Create the input dump separately using the deployment's reviewed read-only backup
procedure. Existing source, key and output paths are preserved; every output
must be new and its parent must exist. The key is read from its file and never
printed. Copy it to separately protected recovery storage, apart from the token;
never commit it or paste it into commands/logs. Losing it prevents decryption.
Do not put decrypted production dumps in Git, public directories or shared temp.

The tool exits 0 only after writing/flushing the complete new file. Authentication,
size and I/O failures exit 1 with static diagnostics; CLI syntax errors exit 2.
Wrong keys or corruption create no plaintext. An I/O failure can leave a partial
new file; treat exit 1 as unusable and inspect only that owned artifact. No file
cleanup is automatic. Fernet tokens expose creation time and approximate size.

Plaintext is limited to 16 MiB, encrypted input to 24 MiB. This deliberately fits
small demo artifacts in memory. Use a reviewed streaming backup tool for large
datasets; this is not a whole-stack backup or an off-host storage service.
Test actual restore before relying on a copy. Source permissions, database
consistency, scheduling, retention, upload/database coordination and off-host
access are separate operational responsibilities.

The [2026-10-19 synthetic restore acceptance](portable-restore-2026-10-19.md)
verified Windows encryption, Linux decryption and PostgreSQL custom-dump restore
without touching deployment data. It does not establish off-host recovery.
