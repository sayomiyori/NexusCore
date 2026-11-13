# Root Telegram E2E activation runbook

Status: **Planned**. This document describes a future activation; it does not
enable anything. Live activation requires its own explicit approval, a verified
public HTTPS origin and the operator actions below. No flag is turned on, no
webhook is installed and no Telegram or provider call is made by this file or
by the Slice 1–2 code.

Status vocabulary: **Implemented** (behaviour exists), **Verified** (covered by
a recorded acceptance), **Planned** (agreed design, not executed), **Blocked**
(cannot proceed without a missing decision or credential).

## 1. Closure status

The three README gaps belong to the *standalone* route. The root flow uses the
opt-in platform route instead; the standalone contracts and their
`401`/`401`/`422` boundary checks are retained and are not defects.

| Standalone gap | Status | Closed by |
| --- | --- | --- |
| WebHook API key vs AuthFortress bearer (`401`) | **Implemented + Verified in isolation** | Platform bot routes authorize the bearer through AuthFortress `/tenants/{id}/authorize` |
| HMAC `X-Webhook-Signature` vs Telegram secret token (`401`) | **Implemented + Verified in isolation** | Platform intake `/webhooks/telegram/{bot}` checks the per-bot secret-token digest; HMAC stays on internal hops |
| `/api/v1/query` needs `question` (`422`) and no return path | **Implemented + Verified in isolation** | Signed AgentHub admission → scoped job → signed answer admission → WebHook send worker |

Evidence:

- Static wiring gate: [tests/test_verify_root_telegram_wiring.py](../tests/test_verify_root_telegram_wiring.py), 179 root tests green.
- Root-derived controlled acceptance: [scripts/verify_root_telegram_e2e.py](../scripts/verify_root_telegram_e2e.py), both modes green on 2026-11-13; receipt fields are documented in [isolated-smoke.md](isolated-smoke.md).
- Contract: [root-telegram-e2e.md](../specs/root-telegram-e2e.md).

## 2. Preconditions (all required)

1. Slice 1 and Slice 2 evidence is accepted: the wiring gate is green, both
   root-derived modes passed, and `verify_stack.py` plus
   `verify_telegram_ai.py --scanners` stay green.
2. A public HTTPS origin has been verified through the optional
   [Telegram demo edge](telegram-demo.md). This is temporary preparation, not a
   DNS/TLS/proxy decision.
3. The root stack is fresh or has a rehearsed, reviewed update. Activation does
   not adopt the 2026-10-13 pinned local release implicitly.
4. The operator key checklist from [.env.example](../.env.example) is complete:
   PostgreSQL and Redis credentials, `AUTH_SECRET_KEY`, `WEBHOOK_SECRET_KEY`,
   `BOT_CREDENTIALS_KEY` (Fernet), `WEBHOOK_AGENT_INGRESS_KEY`,
   `WEBHOOK_AGENT_CONTEXT_KEY`, `AGENT_WEBHOOK_REPLY_KEY`,
   `AUTHFORTRESS_WEBHOOK_SERVICE_KEY`, `TELEGRAM_WEBHOOK_ORIGIN`, provider key
   and model settings.
5. An approval record exists: named approver, date, bot/tenant scope, rollback
   owner and the exact revision/image set.

## 3. Ordered activation steps

1. **Keys.** Generate independent random values of at least 32 bytes for the
   service secrets. `BOT_CREDENTIALS_KEY` must be a Fernet key. Never commit,
   paste into chat or write them to logs.
2. **Flags.** Set `PLATFORM_BOTS_ENABLED=true`,
   `PLATFORM_TELEGRAM_ENABLED=true`, `TELEGRAM_AI_ENABLED=true`,
   `TELEGRAM_REPLIES_ENABLED=true` and
   `TELEGRAM_WEBHOOK_ORIGIN=https://<verified-origin>`. Keep
   `PLATFORM_TENANT_ENABLED=true`; enable `PLATFORM_READ_ENABLED=true` only if
   the dashboard reads are part of the approved scope.
3. **Profiles.** Start only the approved profiles:
   `docker compose --profile telegram-ingress --profile telegram-ai up -d`.
   Do not add `-v`, do not prune, do not recreate unrelated services.
4. **Bot registration.** The owner registers one bot from the dashboard. The
   backend verifies the token through `getMe`; a rejected token stops the run.
5. **Provisioning dry-run.** Run the preparation check and review the result.
   The dry-run must report ready and must not produce a `setWebhook` effect.
6. **Approved `setWebhook` apply.** With the approval record present, apply
   setup for that one bot and confirm the stored status is `configured`.
7. **One human private test message.** The operator sends one plain-text
   private message to the bot. No group, media, edited message or conversation
   history is in scope.
8. **Observe four durable receipts** (read-only queries):
   - `platform_ingress_outbox` reaches `published`;
   - `telegram_ai_jobs` reaches `completed` with one usage row;
   - `telegram_reply_outbox` reaches `published`;
   - `telegram_answers` reaches `succeeded` and the canonical send payload is
     observed exactly once.
9. **Record the outcome.** Attach the receipt path, correlation IDs,
   timestamps, the exact revision and the observed statuses to the approval
   record. Stop.

## 4. Rollback

- Set the four platform flags back to `false`; also disable
  `PLATFORM_READ_ENABLED` if it was enabled for this run.
- Stop the `telegram-ai` and `telegram-ingress` profiles. Keep databases,
  volumes, uploads and receipts.
- Do **not** delete volumes, databases or rows, and do not edit stored webhook
  state directly.
- The Telegram webhook stays installed on Telegram's side after a local
  rollback. Removing it (`deleteWebhook`) is a separate reviewed operation with
  its own approval because it changes an external effect.
- Re-run the standalone smoke and the root-derived driver before any second
  activation attempt.

## 5. Never do

- Never automatically resend an `unknown` or unconfirmed outcome. Recovery uses
  the reviewed recovery paths, not an ad-hoc retry.
- Never stamp or rewrite an existing database, migration head or platform
  receipt to make a check pass.
- Never fall back to paid inference when a quota is exhausted; stop and report.
- Never enable these profiles on the adopted local release without a fresh or
  rehearsed stack.
- Never place secrets in tickets, chat, logs or receipts.

## 6. Evidence to attach

Approval record, exact commit/image revision, `.env` key *presence* (never
values), the four receipt queries and their results, the canonical send
observation, both Slice 1–2 receipts, and the rollback owner confirmation.
