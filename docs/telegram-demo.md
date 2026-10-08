# Preparing a Telegram demo origin

The optional `docker-compose.telegram-demo.yml` overlay adds an nginx edge and
an opt-in Cloudflare Quick Tunnel. It does not enable application flags, run AI
workers, register bots, install a webhook, or send messages. Service repositories
remain independent. This is temporary demo infrastructure, not a production
deployment.

Verified on 2026-10-08: the isolated Docker edge check passed, including routing,
request limits, credential header handling and upstream failure. Root API dry-run
with the reserved `https://demo.example.com` origin returned 200; an unauthenticated
request returned 401 and the bot's webhook row count stayed zero. The temporary
flags were restored and the API remained healthy. This establishes local
preparation behavior only.

The same session's Quick Tunnel connected intermittently but both external
probes returned HTTP 530, with DNS/TLS/edge reconnect errors in cloudflared logs.
The edge/tunnel containers were stopped and removed. No live webhook was changed;
a usable public origin and real-destination dry-run remain required.

The edge permits only `POST /webhooks/telegram/<registered bot UUID>` and forwards
it to WebHook Manager. Other bots, query strings, encoded path aliases, management
APIs, docs and health endpoints are unavailable through the edge. Requests are
limited to 1 MiB with network inactivity timeouts and 16 concurrent requests. These
timeouts are not an absolute request deadline. Only
content metadata and the Telegram secret header reach the API; the API remains
responsible for secret authentication and tenant checks. Request logs are disabled.

## Local verification

Use an existing service image that contains Python, or another trusted Python
image. The check creates its own Docker networks and mock HTTP receiver, reads
no `.env`, and removes its own containers/networks on exit. It contacts no
Telegram or LLM API and touches no application database.

```powershell
docker pull nginx:1.30.5-alpine
python scripts/verify_telegram_edge.py --python-image <existing-python-image>
```

It checks the real nginx configuration: exact route, method/body restrictions,
missing/wrong/duplicate secrets, stripped authorization/cookies, no forwarding of
rejected routes, 16 occupied request slots with rejection of the 17th, idle-body
timeout, invalid UUID configuration, safe logs, and upstream outage.
The idle-body check accepts either 408 or a closed connection within the timeout
window after 100 Continue; nginx may close an incomplete body without a final
HTTP response.

## Prepare the origin

Set `TELEGRAM_DEMO_BOT_ID` to the UUID returned by the local bot registration API.
Do not use the numeric Telegram bot ID or place a token in this variable.

```powershell
$env:TELEGRAM_DEMO_BOT_ID = '<registered-bot-uuid>'
$demo = @('-f', 'docker-compose.yml', '-f', 'docker-compose.telegram-demo.yml')
docker compose @demo config --quiet
docker compose @demo up -d --no-deps --wait telegram_edge
docker compose @demo --profile telegram-tunnel up -d --no-deps telegram_tunnel
docker compose @demo logs --tail 40 telegram_tunnel
```

On the already adopted local host, retain both ignored image overrides before
the demo overlay:

```powershell
$demo = @('-f', 'docker-compose.yml',
          '-f', '.venv/root-adoption.compose.yml',
          '-f', '.venv/root-auth-update.compose.yml',
          '-f', 'docker-compose.telegram-demo.yml')
```

Neither new service publishes a host port. The tunnel can reach only the edge
network; the edge resolves `webhook_service` through Docker DNS, including after
an API recreation. Do not target the complete WebHook API directly from a tunnel.

A generated `trycloudflare.com` URL is not proof of connectivity. Require a
registered tunnel connection, an external POST to an unrelated path returning
404, and the bot path rejecting a missing/invalid secret before proceeding.
Quick Tunnels may stop or change address. DNS/TLS/edge connection errors block
live acceptance; do not keep restarting tunnels and treat an old URL as current.

## Provisioning boundary

The existing provisioning endpoint requires both `PLATFORM_BOTS_ENABLED=true`
and `PLATFORM_TELEGRAM_ENABLED=true`, including for `dry_run=true`. Set
`TELEGRAM_WEBHOOK_ORIGIN` to the verified HTTPS origin. For a preparation-only
check, apply these settings temporarily to `webhook_service`, keep reply/AI
flags and dedicated workers disabled, and restore the original settings in a
`finally` cleanup. Wait for API health before sending requests.

With a fresh owner bearer, call:

```text
POST /api/v1/tenants/<tenant-uuid>/bots/<bot-uuid>/webhook
{"dry_run": true}
```

Expected: HTTP 200, `dry_run: true`, `operation: setWebhook` and the exact URL
`https://<current-origin>/webhooks/telegram/<bot-uuid>`. The operation performs
authorization/read checks but no webhook write or Telegram call. Record a
sanitized result; never save the bearer or dump request headers.

Before applying, inspect existing Telegram webhook state privately. Installing
the new URL replaces that bot's current Telegram destination. Present the exact
new destination and successful dry-run for approval, as required by
`specs/telegram-ai-reply.md`. A dry-run does not authorize `setWebhook`.

The local webhook record retains its original URL with ordinary requests. The
updated WebHook Manager API accepts optional `replace_url: true` in both dry-run
and apply to move to the current operator-configured origin. It preserves the
secret, rejects concurrent setup and does not repeat an already configured target.
A failed/ambiguous replacement retains the new target for ordinary retry. Intake
continues checking the preserved secret during configuring/unknown; a definite
failure blocks intake with 403 until retried. Pending updates are not explicitly
dropped. The adopted local API/worker image was updated on 2026-10-08, retaining
its previously tested dependencies. Other deployments need the updated service
image before using this field. Live AI/reply acceptance also needs its
reviewed worker configuration, bounded inference/send limits and a human message.

Local replacement verification: owner login and `dry_run=true, replace_url=true`
returned 200 with the exact reserved example origin; no bearer returned 401 and
a non-boolean replacement flag returned 422. The webhook row count remained zero.
After restoring disabled flags, all three root API health endpoints returned 200.
The service suite passed 316 tests (84.94% coverage), Ruff and strict mypy; the
11 provisioning tests also passed inside the deployed image with disposable
PostgreSQL/Redis. No real `setWebhook` or message delivery was attempted.

## Continuous operation

A local computer and a Quick Tunnel cannot provide continuous public service:
sleep, shutdown, network loss and changing origins interrupt delivery. The current
setup remains a local development environment until a host and domain are supplied.
Do not enable live AI workers indefinitely merely to hide these interruptions.

For the future persistent deployment, use an always-on host and a stable HTTPS
hostname, retain PostgreSQL/Redis data, configure restart policies and TLS renewal,
and verify backup restoration and recovery after a reboot/network outage. The
domain can point to a direct reverse proxy or an explicitly configured named
tunnel. Choose and verify this when the actual VPS/domain are available; a named
tunnel on a sleeping desktop does not solve host availability.

## Close preparation

```powershell
docker compose @demo stop telegram_tunnel telegram_edge
docker compose @demo rm -f telegram_tunnel telegram_edge
```

Restore the original API flags/origin and check `/health/ready`. Use the complete
retained override list when recreating the API. Do not run `down` on the root
project or remove database volumes. Stopping a tunnel does not uninstall an
existing Telegram webhook; changing that external state requires its own reviewed
operation. Keep credentials and temporary origins out of committed files.

References: [nginx HTTP core directives](https://nginx.org/en/docs/http/ngx_http_core_module.html)
and [official nginx image templates](https://hub.docker.com/_/nginx).
