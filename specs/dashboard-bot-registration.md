# Dashboard bot registration boundary

Allow a signed-in tenant owner to register a bot through the existing WebHook
Manager API. Members remain read-only. The browser submits a name and token to a
same-origin BFF; the BFF validates origin, session, tenant, bounded fields and
fresh issuer membership, then makes exactly one scoped WebHook registration
request. WebHook Manager remains authoritative for `bot.manage`, Telegram getMe,
encrypted storage, duplicate detection and post-verification authorization.

The server projects only safe bot metadata. No token, Telegram identity, URL,
ciphertext, upstream response body or exception text is returned or logged.
Registration does not configure a webhook, enable workers or activate providers.
Uncertain outcomes must not be automatically retried: users refresh the inventory
before deciding what to do. The form clears the token before awaiting the server.

The BFF accepts only
`POST /api/bot-registration?tenant=<canonical UUID>` and exactly `{name, token}`;
reject duplicate/extra fields, unsafe origin, no session, malformed input, members
and foreign membership before any WebHook call. Enforce the backend token grammar,
Unicode name limit and the upstream 4 KiB request-body limit. Only an exact upstream HTTP 201 with
matching tenant, valid ID, expected normalized name, active status and
`not_configured` webhook state confirms success. Respond with safe metadata; any
transport, malformed acknowledgement or unexpected status is an unconfirmed 502.
Never repeat the POST. Preserve upstream 400/401/403/404/409/429 without provider
messages. No dependency, schema migration, root deployment or real Telegram call.

The owner-only UI on the existing Bots view has explicit unconfirmed-outcome
copy, local validation and token cleanup, navigation locked during submission,
existing first-page refresh on success. Tests cover cross-tenant/member/CSRF,
malformed inputs and responses, duplicate statuses, timeout, privacy and no retry;
test UI and actual BFF against a new isolated fixture using synthetic getMe.
