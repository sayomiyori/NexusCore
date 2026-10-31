# Stage G supply chain and worker hardening — acceptance (2026-10-31)

Receipt for `specs/supply-chain-hardening.md`. NexusCore-owned files only:
`docker-compose.yml`, `docker-compose.telegram-demo.yml`, the runtime test and
the docs. The live stack was not recreated.

## Digest pins

Resolved with `docker buildx imagetools inspect` for the exact tags:

| Image | Digest |
| --- | --- |
| `pgvector/pgvector:pg16` | `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a` |
| `redis:7-alpine` | `sha256:8da19c7399dca900c6822a1cf30f9d2285585e2c4b457ff4095b0f4500054d3f` |
| `nginx:1.30.5-alpine` | `sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94` |

`cloudflare/cloudflared` was already pinned. Both Compose files now fail the
runtime test if any `image:` line lacks a `@sha256:` pin.

## Worker and datastore limits

- `x-worker-hardening` (`cap_drop: ["ALL"]`, `tmpfs: ["/tmp"]`,
  `pids_limit: 256`) on exactly the ten worker/recovery services; none of them
  became `read_only`.
- `postgres` `pids_limit: 512`, `redis` `pids_limit: 128`; no `cap_drop` or
  `read_only` on either, because the PostgreSQL entrypoint needs
  `CHOWN`/`SETUID`/`SETGID` during init and both need writable data volumes.
- `docker compose --profile "*" config` resolves: 15 services, 13 with
  `cap_drop: ALL` (3 API + 10 workers), 15 with a `pids_limit`.

## Dynamic check

Built images were started against disposable `pgvector/pgvector:pg16` (with
`init-scripts`, which created the service roles) and `redis:7-alpine` on
`nexuscore_nexus_net`:

| Container | Flags | Result |
| --- | --- | --- |
| `webhook_worker` | `--cap-drop ALL --tmpfs /tmp --pids-limit 256 --security-opt no-new-privileges:true` | `Connected to redis://hardredis:6379/2`, `celery@f06d46ad729d ready.`, container running |
| `agent_worker` | same | `Connected to redis://hardredis:6379/3`, `celery@15ca331b8b46 ready.`, container running |

`grep CapEff /proc/1/status` returned `0000000000000000` in both, i.e. the
process really ran with an empty effective capability set. Containers and their
synthetic env were deleted afterwards.

## Not covered

- Application images from the sibling build contexts remain unpinned (local
  builds).
- No live-stack recreate, so the pins and limits are not yet active in the
  running demo containers; they apply on the next `docker compose up -d`.
- Backend `/docs`, `/openapi.json`, `/metrics` gating is still blocked on the
  sibling repositories' uncommitted work.
