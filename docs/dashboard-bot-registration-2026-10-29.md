# Dashboard bot registration acceptance — 2026-10-29

Owners can register a bot using the existing scoped WebHook Manager endpoint.
The dashboard BFF validates Origin, session, tenant, exact request fields and
fresh issuer membership before a single upstream POST. The backend repeats the
authorization after verification and encrypts the token. Members cannot use the
form or endpoint. The BFF returns only validated safe metadata and requires a
matching HTTP 201 acknowledgement. A lost or malformed acknowledgement is shown
as unconfirmed and blocks another form submission until the user refreshes the
inventory. Registration does not provision a webhook or activate processing.

From `dashboard/`:

```powershell
npm test
npm run lint
npm run typecheck
npm run build
npm audit
node --test tests/bot-registration.test.ts
```

The suite passed 70 tests, Biome checked 48 files, typecheck/build passed and npm
audit reported zero vulnerabilities. Registration HTTP tests cover safe success,
owner/member and issuer denial, malformed input, CSRF, tenant mismatch, malformed
acknowledgements, unexpected statuses, lost acknowledgement and no automatic retry.
Independent adversarial/security review found and rechecked two fixed issues:
unexpected 422 mapping and the obsolete read-only sidebar label. Its final pass
reported no remaining findings.

## Isolated acceptance

Docker Engine 29.8.2 was used after read-only inventory. Commands from the root:

```powershell
python .venv/inventory_bot_registration_20261029.py before
python .venv/verify_bot_registration_20261029.py
python .venv/inventory_bot_registration_final_20261029.py before
python .venv/verify_bot_registration_final_20261029.py
python .venv/inventory_bot_registration_final_20261029.py after
```

These private ignored helpers are workstation-specific evidence collectors.
They use fresh UUID Compose projects, separate volumes, internal networks,
synthetic identities, and a Telegram MockTransport restricted to one fictional
token. No external Telegram, LLM or webhook provisioning was invoked.

The first fixture failed before registration: its inherited controlled receiver
origin used loopback, rejected by the fixture safety guard. No bot was inserted;
the six owned containers stopped cleanly. The second fixture used its own
internal callback address. Real dashboard, AuthFortress, WebHook Manager and
PostgreSQL then confirmed owner registration, hidden member form, member and
foreign-tenant POST denial, missing-session denial, one upstream POST, an active
stored bot with encrypted credential, and unchanged other fixture data. Browser
tests also verified cleared token input, no webhook setup, owner/member behavior,
360 CSS pixels without horizontal overflow and no console warnings/errors.
Final sidebar wording was checked in the production build with a local synthetic
issuer, after the isolated fixture stopped.

The final baseline had 860 containers, 459 volumes, 105 networks and 13 running
containers. After the new fixture, original container/volume/network records,
main database/schema/row/sequence and uploads fingerprints, protected files and
WSL settings matched. All six newly owned containers stopped with exit 0, no OOM.
A concurrent unrelated container appeared during acceptance; the strict initial
comparison rejected that addition. A second comparison verified original records
and selected the six owned containers by project label. The other container was
left untouched. No Docker resources were deleted.

This is synthetic local acceptance, not public deployment or a live Telegram
test. Existing main and sibling data, unrelated working-tree changes and WSL
settings are outside the implementation.
