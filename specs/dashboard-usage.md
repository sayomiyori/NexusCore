# Read-only per-bot Usage dashboard

Connect the next roadmap section to AgentHub's existing opt-in tenant/bot usage
read contract. Show recorded token counts and exact estimated USD for one active
bot and a bounded UTC date interval. Reads do not enable AI processing. Preserve
all deployments, provider settings, WSL, foreign work and independent services.

## Contract and minimal design

- Add `GET /api/usage?tenant=UUID&bot=UUID&start=YYYY-MM-DD&end=YYYY-MM-DD`.
  Exactly one value for each key, no extras; canonical lowercase UUIDs and real
  canonical dates (year 0000 forbidden). Start is inclusive UTC midnight, end
  exclusive UTC midnight; interval must be positive and at most 31 days.
  Guard Host/session before upstream calls and validate all input before reads.
- Freshly authorize tenant through existing AuthFortress helper, then GET
  AgentHub `/api/v1/tenants/{tenant}/bots/{bot}/ai/usage` with explicit timezone-
  aware start/end, same bearer and canonical tenant header. AgentHub remains
  authoritative for ai.read and fresh active bot context. Never query global
  usage or infer authorization from the UI. New server-only `DASHBOARD_AGENT_ORIGIN`
  reuses existing private numeric origin/direct/no-proxy/no-redirect/5s/body cap.
- Project only tenant, bot ID, normalized interval, nonnegative safe-integer
  records/inputTokens/outputTokens, exact estimatedCostUsd decimal string.
  Accept bounded nonnegative Decimal representations, including `0E-8`/`1E-8`,
  normalize to eight fractional digits with integer arithmetic, never round via
  floating point. Reject malformed/nonfinite/negative/excess precision/oversize
  values. No provider/model/raw usage/message/answer/credential fields.
- Add native Usage navigation. Reuse the existing paged safe Bots DTO for an
  active-bot selector, Next page/First page and names. Explain active-only and
  50-record page limits, including pages with no active bots. Do not scan pages
  automatically or invent a tenant-wide total. Four mobile tabs wrap safely.
- Native UTC date inputs default to the current UTC day [today,tomorrow).
  Load usage is explicit. Changing bot/date inputs aborts and clears prior
  result/error; parent Refresh/tenant/section/page changes unmount and reset the
  form. Ignore stale responses and expire shared session on401.
- Show loading, no result, successful zero usage, malformed/unavailable/denied
  states distinctly. Never substitute zeros on failure. Label estimates as
  recorded estimates, not invoices, real-time bills or lifetime totals. No
  provider price assumptions, job replay, bot editing or LLM activation.

## Acceptance

1. Existing29tests plus HTTP BFF regressions cover exact paths/headers/UTC bounds,
   all input denial before calls, fresh/revoked/foreign authorization, source
   failures, Decimal exactness/zero/scientific forms, malformed integers and safe
   projection. Strict tsc, Biome, production build and full/runtime audits pass.
2. A new small internal fixture uses actual AuthFortress/WebHook/AgentHub reads
   with only synthetic bot/jobs/usage in new databases and providers disabled.
   Verify nonzero/zero intervals, start-inclusive/end-exclusive, cross-bot/tenant
   isolation, read-only fingerprints and outage/recovery/logout. No main rollout.
3. Production browser desktop/360 checks cover navigation, active bot/date
   controls, explicit load/clear/reset, exact money text, zero/error/expiry,
   stale responses and preserved existing sections. Capture actual screenshot,
   close only owned processes, retain fixture data and prove baseline equality.
4. Fresh independent read-only adversarial/security review, scoped commit/push
   and exact Windows/Ubuntu dashboard CI. Document exact commands/results and
   what was not checked.

Safe defaults: one bot at a time; UTC calendar-day inputs; existing active bot
context restrictions. Account-wide billing, provider configuration, arbitrary
job details and tenant-wide aggregation need separate contracts.
