# Read-only recent Events explorer

Add the next dashboard section after Overview and Bots: inspect and filter the
existing authorized recent observation window. Reuse `GET /api/overview`, its
fresh issuer membership check, bounded receiver reads and safe DTO unchanged.
No new backend route, provider call, dependency, storage, polling or history
scan is needed. This is recent observation inspection, not a complete audit log.

## Contract and design

- Native Events navigation shares existing organization selection, session,
  Refresh and sign-out. Selecting Events fetches the same existing bounded
  observation DTO; section/tenant/Refresh changes clear old data and filters,
  abort pending reads and ignore stale responses.
- Show at most the existing ten merged observations. Preserve time order,
  relay-ID deduplication, source availability and conflict evidence. A receiver
  response does not establish live bot/service health or lifetime totals.
- Filter only loaded observations by source kind (all/auth/webhook/agent),
  responding receiver, event/bot UUID substring (case-insensitive, trimmed,
  at most 36 input characters), and failed/unknown/conflicting attention.
  Filters combine with AND, do not issue requests and do not mutate data.
  Reset filters restores the loaded window. Make the loaded-window limit clear.
- Rows show fixed event type/state labels, full canonical event/bot IDs,
  normalized UTC time, receiver names and validated AI attempt counts where
  present. No raw payload/log/preview, free-form errors, credentials, provider
  data, messages or event replay/reconciliation controls enter the screen.
- Separate no supported observations, no filter matches and unavailable reads.
  Preserve the partial-source warning and explicitly show responding receivers.
- Use native labeled controls, keyboard focus, existing design tokens and
  responsive wrapping from 360 px. Extract shared labels/attention predicate
  only because existing Overview/Bots and Events now need them.

## Acceptance

1. Existing 26 Node tests remain green. Focused tests prove combined filters,
   case/whitespace UUID queries, attention/conflict behavior, empty input,
   preserved order and immutable source records. Existing HTTP tests still prove
   fresh authorization, cross-tenant denial, redaction and partial outages.
2. TypeScript, Biome, production build and npm audits pass. A fresh read-only
   adversarial/security reviewer checks actual code and runs relevant checks.
3. Production browser acceptance uses only synthetic fixture data: desktop and
   360 px navigation, all filters/reset, full IDs, no-match/empty/unavailable,
   tenant/section switching and logout. Prove filters do not make source calls.
   Use actual AuthFortress/EventPipe/PipeWatch if a fresh isolated fixture can
   start safely; record explicit limits rather than treating fakes as real APIs.
4. Preserve existing deployment data/WSL/resources and foreign WIP. Stop only
   owned test processes, retain fixture data, record exact checks and screenshot,
   then commit/push this scope and verify Windows/Ubuntu dashboard CI.

Safe assumption: the already approved safe recent window is the first useful
Events increment. Historical search, arbitrary filters on raw logs and broader
event types require a separately specified backend contract.
