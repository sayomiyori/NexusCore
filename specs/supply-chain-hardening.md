# Supply chain and worker hardening (Stage G)

This increment closes the last two Stage E/F residuals that are fully owned by
NexusCore: third-party images were tag-pinned only, and Celery worker containers
ran with the full capability set and no PID ceiling. Backend `/docs`,
`/openapi.json` and `/metrics` gating still waits on the sibling repositories.

## Digest pins

External images keep their human-readable tag and add the registry digest, so a
republished tag cannot silently change what runs:

- `pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`
- `redis:7-alpine@sha256:8da19c7399dca900c6822a1cf30f9d2285585e2c4b457ff4095b0f4500054d3f`
- `nginx:1.30.5-alpine@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94`

`cloudflare/cloudflared` was already digest-pinned. Digests are the
multi-platform index digests returned by `docker buildx imagetools inspect` for
the exact tag, so the pin works for both amd64 and arm64 hosts. Application
images built from the sibling build contexts are out of scope: they are built
locally, not pulled.

## Worker containers

`x-worker-hardening` (`cap_drop: ["ALL"]`, `tmpfs: ["/tmp"]`,
`pids_limit: 256`) is applied to all ten worker and recovery services:
`webhook_worker`, `webhook_delivery_recovery`, `webhook_outbox_recovery`,
`agent_worker`, `agent_telegram_worker`, `agent_telegram_recovery`,
`agent_reply_worker`, `agent_reply_recovery`, `webhook_sender`,
`webhook_send_recovery`.

Workers deliberately keep a writable root filesystem: Celery writes bytecode and
spool files, and `read_only` there would need its own investigation.

## Datastores

`postgres` gets `pids_limit: 512` (a backend forks per connection) and `redis`
gets `pids_limit: 128`. Neither gets `cap_drop` or `read_only`: the official
PostgreSQL entrypoint needs `CHOWN`/`SETUID`/`SETGID` during initialisation and
both need writable data volumes.

## Verification

- `tests/test_verify_runtime_hardening.py` now has seven checks: required
  PostgreSQL credentials, the bounded logging anchor on all 15 services, the
  API anchor on exactly the three API services, the worker anchor on exactly the
  ten workers with no `read_only`, datastore `pids_limit` values with no
  capability/filesystem changes, and a digest on every external `image:` line in
  both Compose files.
- Dynamic check: the built `webhook_worker` and `agent_worker` images were run
  with `--cap-drop ALL --tmpfs /tmp --pids-limit 256
  --security-opt no-new-privileges:true` against disposable PostgreSQL/Redis
  containers. Both reported `celery@… ready.` after connecting to the broker and
  `/proc/1/status` showed `CapEff: 0000000000000000`.

## Residuals

- Application images built from `../AuthFortress`, `../WebHook_Manager` and
  `../AgentHub` are not digest-pinned; they are local builds.
- Workers are not `read_only` and have no memory limits.
- `postgres` and `redis` keep their default capability sets.
- The live stack was not recreated, so the new pins and limits take effect on the
  next `docker compose up -d`.
