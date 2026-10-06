# Free AI providers for the demo

Checked 2026-10-06. Existing credentials stay in local `.env`; never commit tokens.

| Provider | Direct API evidence | AgentHub integration |
| --- | --- | --- |
| Groq | Authenticated model catalog; configured model available | Local Groq adapter; current root Compose selects it |
| Gemini | gemini-2.5-flash returned complete text | Existing standalone adapter; root does not forward its key |
| OpenRouter | liquid/lfm-2.5-2.6b:free returned complete text, reported cost 0 | Adapter/config wiring pending |
| Cloudflare Workers AI | llama-3.2-3b-instruct returned text | Adapter/config wiring pending |

Gemini Free Tier and Cloudflare Workers Free were operator-confirmed. OpenRouter
key metadata reported Free Tier and 50 daily requests before probes. This is direct
provider evidence, not a guarantee of billing history, availability or the full
Telegram scenario. Quotas and catalog entries can change.

## Variables and scope

- `GROQ_API_KEY`: currently forwarded by root Compose to AgentHub API/worker.
- `GEMINI_API_KEY`: consumed by standalone AgentHub generation/embedding adapter.
  The provider probe used the key in AgentHub's local `.env`.
- `OPENROUTER_TOKEN`: probe used the root `.env`; reserved for a future adapter.
- `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`: root `.env`, reserved for a
  future adapter. Use the Workers AI template scoped to one account, Read/Edit
  permissions. An account token verifies through the account-token endpoint,
  not the user-token endpoint. Billing-read permission is unnecessary.

Keep `LLM_FALLBACK_PROVIDER`/`LLM_FALLBACK_MODEL` empty for this demo. Existing
standalone code accepts paid adapters if explicitly configured; it is not a
free-only enforcement boundary. Initial platform processing is Groq-only under
[the approved contract](../specs/telegram-ai-reply.md). No automatic cross-provider
retry after an uncertain generation outcome.

## Quotas and selection

[OpenRouter Free](https://openrouter.ai/pricing) allows 50 requests/day. Only select
existing catalog variants ending in `:free` with verified zero pricing; the probe
also restricted max_price to 0 and disabled provider fallback. A 16-token cap
exhausted reasoning without a final answer; 256 tokens produced complete output.
Do not assume every model supports disabling reasoning.

[Cloudflare Workers Free](https://developers.cloudflare.com/workers-ai/platform/pricing/)
includes 10,000 Neurons/day. Some models require paid billing. Stay on Free and use
only eligible models. [Token setup](https://developers.cloudflare.com/workers-ai/get-started/rest-api/)
requires an account ID and a limited Workers AI token; no Worker deployment is
required to use REST inference.

[Gemini Free Tier](https://ai.google.dev/gemini-api/docs/billing) supports selected
models with [project/model quotas](https://ai.google.dev/gemini-api/docs/rate-limits).
Confirm the project has no paid billing before generation. A valid key/catalog
response alone does not establish generation quota or account billing tier.

## Future UI

Provider token onboarding remains planned: tenant-scoped encrypted storage,
masked provider/account metadata, authorized validation and no token readback.
Do not put tokens in frontend bundles, prompts, events, queue payloads or logs.
List-price token estimates and actual demo billing are separate measurements.
