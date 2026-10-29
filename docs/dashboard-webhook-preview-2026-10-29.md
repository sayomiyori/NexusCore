# Webhook preparation check acceptance — 2026-10-29

Owners can check preparation of an active registered bot through a constrained
dashboard BFF. The BFF accepts an exact empty JSON object and always sends only
`{dry_run:true}` to the existing backend. It verifies fresh issuer ownership,
canonical tenant/bot IDs and a matching backend acknowledgement. It excludes
the webhook URL and all secrets from its response. Members do not see the
control. This check does not configure a webhook or prove endpoint reachability.

From `dashboard/`:

```powershell
npm test
node --test tests/webhook-preview.test.ts
npm run lint
npm run typecheck
npm run build
npm audit
```

74 tests passed; the focused four-test suite covered owner/member, CSRF, bad
scope/body, attempts to send `dry_run:false`, malformed/mismatched response,
empty query/fragment delimiters and backend failure without retry or disclosure.
Biome checked 51 files; typecheck/build passed and npm audit reported zero
vulnerabilities. Independent read-only security review found no remaining issue
and repeated the focused tests, lint and typecheck.

## Isolated acceptance

Docker Engine 29.8.2 was used after a fresh read-only inventory. Workstation-only
ignored evidence helpers were run from the repository root:

```powershell
python .venv/inventory_webhook_preview_20261029.py before
python .venv/verify_webhook_preview_20261029.py
python .venv/inventory_webhook_preview_final_20261029.py before
python .venv/verify_webhook_preview_final_20261029.py
python .venv/inventory_webhook_preview_final_20261029.py after
```

The first owned fixture exposed a Next.js transport difference: a zero-length
HTTP POST still had a non-null body stream and was rejected before authorization.
It was stopped cleanly and not accepted. The BFF now requires an empty JSON object
using the existing bounded parser, and a fresh isolated fixture repeated the
checks. It enabled the Telegram platform mode only inside the new internal
network, using synthetic URL and credentials; no worker or live provider was
enabled and no existing deployment was modified.

The production dashboard BFF, AuthFortress and WebHook Manager passed owner
dry-run, member and foreign-tenant denial and missing-session denial. In the
browser, the member had no preview button; the owner saw a passing check for an
active bot and the result cleared on leaving the section. A 360 CSS pixel
viewport had no horizontal overflow and the console had no warnings/errors.
Before/after fixture fingerprints matched, no webhook row was created, and the
controlled receiver recorded no webhook setup, Telegram send or LLM effect.

Baseline: 873 containers, 465 volumes, 107 networks, 14 running containers and
80 stopped scanners. After stopping six owned containers with exit 0 and no OOM,
all baseline resource records, main databases/schema/rows/sequences, uploads,
protected files and WSL fingerprints matched. Existing images remained present;
the 80 existing scanners remained stopped. No resource was deleted.

This local dry-run acceptance is not a live Telegram provisioning, public
deployment, webhook reachability test or production readiness claim.
