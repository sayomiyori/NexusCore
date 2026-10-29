# Owner-only webhook preparation check

Let a tenant owner check whether an active registered bot can be prepared for
webhook provisioning. The dashboard invokes only the existing WebHook Manager
`dry_run=true` operation: it must never send `dry_run=false`, replace a URL,
configure Telegram or enable ingress. This is a readiness preview, not evidence
that a webhook is configured or reachable.

Use a same-origin `POST /api/bot-webhook-preview?tenant=UUID&bot=UUID` with an
exact empty JSON object. Guard Origin, session and canonical scope, then check fresh issuer
membership and owner role before posting exactly `{dry_run:true}` to the scoped
backend endpoint. The backend rechecks owner permission and bot membership.
Require HTTP 200, matching tenant/bot, literal `dry_run:true`, `operation` equal
to `setWebhook`, and a syntactically valid HTTPS webhook URL for that bot. Do not
return the URL, token, webhook secret or provider messages to the browser.
Any malformed or mismatched acknowledgement fails closed; do not retry.

Only active bots in the owner view show the explicit preview button. Report a
successful preview as a preparation check, not activation. Members see no
control. On failure, show a bounded error; expired sessions return to sign-in.
Tenant/section changes abort stale reads and do not display previous results.
Test owner, member, expired/forged scopes, invalid acknowledgement and backend
outages; prove requests cannot select `dry_run=false` and no Telegram calls or
database writes occur. Use only a fresh isolated fixture and synthetic data.
