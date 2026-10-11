# Local legacy delivery recovery rollout

Status: applied and verified on 2026-10-11 after explicit approval of the exact
local scope. This is the deployment continuation of
[the verified recovery increment](legacy-delivery-recovery-2026-10-09.md).

## Exact scope

- Local `webhook_manager` on `127.0.0.1:25432`: forward migration
  `3cc3bb772105` -> `6e2f8a1c9b04`.
- Replace only `webhook_service` and `webhook_worker`; add
  `webhook_delivery_recovery` with the opt-in `legacy-recovery` profile.
- Use the previously tested image
  `sha256:ab554e0bd43039a179f7aa7c09756fefd394b9539dd7dce05665a4ba3cff61e7`
  for all three processes. The ignored `.venv/root-delivery-recovery.compose.yml`
  pins it; retain the existing adoption and Auth overrides, in that order.
- Preserve every existing row, old column, index, constraint, sequence value and
  `is_called`, owner, ACL, volume, upload and unrelated process.
- Keep platform bot registration, Telegram intake, replies, AI and read flags
  disabled. Do not start Telegram/AI profiles or a public proxy.

The scanner can publish legacy deliveries independently of these platform flags.
Inventory its recoverable rows and destinations before every activation; unknown
destinations or ambiguous historical effects require a separate decision.

## Current inventory and rehearsal

The pre-rollout read-only inventory found 14 `SUCCESS` deliveries, no pending/retrying/failed
or delivering rows, and zero queued or unacknowledged Celery messages. Auth,
WebHook readiness and AgentHub health each returned HTTP 200. The root WebHook
processes used `e4008fbd...` and revision `3cc3bb772105`.
All broker list queues, including priority queues, are empty; the worker reports
zero active, reserved and scheduled tasks. Unauthenticated legacy delivery reads
return 401; disabled platform intake returns 503.

A fresh custom-format dump was encrypted with Windows user-scoped DPAPI and
successfully decrypted from disk. It was restored on a dedicated PostgreSQL
container using a temporary filesystem and a loopback-only random host port.
Source owner roles were recreated without login or passwords; restore retained
ownership and ACLs. No HTTP worker ran against copied records, and its scanner
used an unreachable broker.

Restored data, schema, sequences, owners and ACLs matched. PostgreSQL reparses four
existing state CHECK expressions from an array-wide varchar-to-text cast to the
equivalent per-element casts; the comparison allows only that exact expression
rewrite for those four named checks. All other definitions compare exactly.

The tested image applied the forward migration, passed `alembic check`, and its
scanner submitted zero deliveries. After migration all 14 original delivery rows
matched with the two new nullable columns removed; those columns remained NULL.
Other rows, old schema definitions, sequence state, ownership and ACLs remained
unchanged. A final read-only comparison confirmed the root database was untouched.

Local artifacts are retained under `.venv/`: `delivery-rollout-inventory.json`,
`delivery-rollout-rehearsal.json`, the encrypted backup and rehearsal scripts.
The encrypted dump is specific to this Windows user and is not a portable backup.

## Applied result

A second fresh encrypted backup/restore rehearsal passed immediately before the
approved update. Its retained encrypted archive is
`.venv/delivery-backup-60567441cb10462899fee9c49fef1fb4/webhook_manager.dpapi`.
After gracefully stopping the two WebHook processes, the guarded procedure
rechecked the exact snapshot, empty broker and absence of other WebHook DB
clients. It applied `6e2f8a1c9b04` and passed `alembic check`.

Before startup it confirmed all 14 old delivery rows, other rows, old schema
definitions, sequence values/`is_called`, ownership and ACLs unchanged. The only
schema additions are two nullable schedule columns and their dispatch index;
successful rows retain NULL schedules. No restore-related CHECK rewrite occurred
in the root database.

The API, worker and scanner now run the exact pinned recovery image. API readiness
returns 200; the worker responds to ping and reports zero active/reserved/scheduled
tasks. Multiple scanner heartbeats report `submitted=0`, with no broker/recovery
or startup error markers. Unauthenticated legacy delivery reads return 401;
disabled platform intake returns 503. Auth and AgentHub health remain 200. Their
containers and PostgreSQL/Redis retain the original IDs, images, mounts, networks
and flags; no existing volume or upload was touched. All live flags remain false.

The sanitized apply and acceptance artifacts are
`.venv/delivery-rollout-apply.log`, `.venv/delivery-rollout-result.json` and
`.venv/delivery-rollout-postcheck.json`. Fresh independent read-only
adversarial/security acceptance returned APPROVE: actual revision/images,
schema/data/sequence state/owners/ACLs, unchanged other containers, empty broker,
worker pong, scanner heartbeat and HTTP refusals passed. It compared all 14 old
delivery rows against both the initial and fresh rehearsal copies and decrypted
the fresh backup in memory. Temporary rehearsal containers/networks were removed
after acceptance; all encrypted backups remain retained.

## Commands executed

From `D:/Programming/NexusCore`:

```powershell
../WebHook_Manager/.venv/Scripts/python.exe -u .venv/inspect_delivery_rollout.py
../WebHook_Manager/.venv/Scripts/python.exe -u .venv/rehearse_delivery_rollout.py
../WebHook_Manager/.venv/Scripts/python.exe .venv/verify_delivery_compose.py
../WebHook_Manager/.venv/Scripts/python.exe -m ruff check .venv/inspect_delivery_rollout.py .venv/rehearse_delivery_rollout.py .venv/verify_delivery_compose.py
../WebHook_Manager/.venv/Scripts/python.exe -m ruff check .venv/apply_delivery_rollout.py
../WebHook_Manager/.venv/Scripts/python.exe -m py_compile .venv/apply_delivery_rollout.py
../WebHook_Manager/.venv/Scripts/python.exe -u .venv/apply_delivery_rollout.py --apply-approved-local
docker compose -f docker-compose.yml -f .venv/root-adoption.compose.yml -f .venv/root-auth-update.compose.yml -f .venv/root-delivery-recovery.compose.yml --profile legacy-recovery config --quiet
git diff --check
```

Results: inventory and both isolated rehearsals PASS, Ruff/compile PASS, Compose
validation exit 0, guarded apply exit 0, diff check exit 0. Independent inline
postchecks captured worker pong, actual three-process image/env/DB/broker equality,
multiple idle scanner heartbeats and zero current startup error markers.

Docker Desktop initially failed at stale `dockerInference` and Secrets Engine
sockets. Their runtime directories were retained as local backups; after moving
both directories with WSL, Docker started and existing containers resumed.
No factory reset, volume deletion or application image replacement was used.

## Approved deployment procedure

Require explicit approval of the exact local scope above before root writes.
Recheck the inventory, worker active/reserved/scheduled task counts and all broker
priority queues. Stop on drift or unresolved deliveries. Create and rehearse a
fresh encrypted backup before the process stop; compare the stopped database to
that backup before migration. A changed snapshot requires a new rehearsal.

Use the four Compose files above for every operation:

1. Gracefully stop only `webhook_service` and `webhook_worker` with a 60-second
   timeout. Confirm no worker task or database client remains active.
2. Run a one-off `webhook_delivery_recovery` container with `--rm --no-deps` and
   command `python -m alembic upgrade 6e2f8a1c9b04`; then `python -m alembic check`.
3. Compare old rows, schema, sequences, owners and ACLs against the rehearsed
   backup. Stop with both application processes down if verification fails.
4. Start the pinned API with `up -d --no-build --pull never --no-deps
   webhook_service`; wait for HTTP readiness 200. Then start the pinned worker
   and scanner with the same options and explicit service names.
5. Verify the three image IDs, worker pong, idle scanner heartbeat, rejected
   unauthenticated legacy API requests, closed platform intake, API health, and
   absence of startup/recovery errors. Compare unrelated container IDs, images,
   mounts, networks and disabled flags to the initial inventory.

Do not automatically downgrade the schema or fall back to the old worker after
migration. Keep the tested new image and repair forward. The API is unavailable
during the bounded process replacement. A root broker-outage injection and live
Telegram/provider traffic are outside this deployment acceptance.
