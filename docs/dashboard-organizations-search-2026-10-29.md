# Organization search acceptance — 2026-10-29

The Organizations directory filters only membership names already loaded in the
browser. The matching and loaded counts are not a total. Loading another page
applies the current search to it; leaving the section or refreshing resets the
search. Selecting a result retains the existing scoped authorization check.

From `dashboard/`, the following checks completed successfully:

```powershell
npm test
npm run lint
npm run typecheck
npm run build
npm audit
```

The suite passed 66 tests, Biome checked 45 files, the build passed, and npm
audit reported zero vulnerabilities. The name filter regression includes case,
Cyrillic text, empty/no-match searches, ordering and source preservation. Fresh
independent adversarial review found no confirmed defect; it repeated tests,
lint and type checking. Browser lifecycle behavior was verified separately.

## Isolated acceptance

Docker Engine 29.8.2 was available on `desktop-linux`. The read-only baseline
captured 844 existing containers, 453 volumes, 103 networks, nine running
containers and 80 stopped scanners. No existing stand was used for the search
tests. The following local ignored helpers capture preservation evidence and
create a fresh UUID-scoped six-service fixture, with internal networking and
synthetic credentials and data:

```powershell
python .venv/inventory_search_20261029.py before
python .venv/verify_organization_search_20261029.py
python .venv/inventory_search_20261029.py after
```

The helpers are workstation-specific evidence collectors, not portable CI tests.
The fixture's production dashboard and real isolated service HTTP endpoints proved
owner membership pages 50+2, a one-member list, missing-session rejection, and
foreign-tenant denial for both owner and member. Separate scoped Knowledge HTTP
checks covered owner/member, empty and foreign tenants, logout and safe projection.
The fixture's controlled Telegram/provider/setup counters remained zero.

In the browser, a name on the second page produced 0 of 50 loaded before loading
more and 1 of 52 afterwards. Opening that organization used the existing scoped
Overview flow. Switching sections and Refresh reset the search. A member's search
returned its own membership and role. At 360 CSS pixels the page had no horizontal
overflow; browser warnings/errors were absent. No live Telegram or LLM was used.

After stopping the fixture, all six owned containers exited 0 without OOM. The
strict first preservation comparison flagged one difference: `open-webui` health
transitioned from `starting` to `healthy`. A second comparison allowed only that
exact health transition and required all other recorded container fields to match.
Original volume/network records, protected files, database/schema/row/sequence
fingerprints, uploads and WSL settings matched. Existing images remained present;
all 80 original scanners were stopped. No resources were deleted.

This is local acceptance of a bounded snapshot filter, not evidence of complete
membership history, production readiness or live provider integration.
