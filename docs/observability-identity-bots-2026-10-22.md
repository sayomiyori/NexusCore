# Identity and bot observation acceptance — 2026-10-22

The opt-in relay now reads authorized AuthFortress tenant metadata and WebHook
Manager bot registry metadata alongside the existing AgentHub job source.
See the [source contract](../specs/observability-identity-bots.md) and
[operator runbook](observability-flow.md). No sibling repository, migration,
dependency, existing deployment or WSL setting was changed.

Source SHA-256:
`de59def38e408bba9288ecf4cababb5abbb2b2470824ce029a9f399e3a5df126`.

## Root checks

```powershell
& .venv/tooling-checks/Scripts/python.exe -B -m unittest discover -s tests -p test_verify_observability.py -q
& .venv/tooling-checks/Scripts/python.exe -B -m unittest discover -s tests -p 'test_verify*.py' -q
& .venv/tooling-checks/Scripts/python.exe -B -m ruff check --no-cache scripts tests
& .venv/tooling-checks/Scripts/python.exe -m compileall -q scripts tests
& .venv/tooling-checks/Scripts/python.exe -B -m pip check
```

Focused tests: **22 OK**. Full root regression: **114 OK in 37.358 s**;
independent reviewer: **114 OK in 34.44 s**. Ruff and compilation passed;
pip reported no broken requirements.

New tests cover the two safe payload allowlists, canonical tenant/bot scope,
strict schemas/aware UTC times, deterministic identities and first-observation
retention, per-source authorization of saved pending events, partial/all-source
failure and inactive bot reporting despite AI denial. Existing AI-only SQLite
binding is reused without schema changes; the golden AI event UUID is unchanged.
Optional CLI origins fail safely before state access when no source is selected.

## Actual Docker fixture

The private driver creates a fresh UUID project with fourteen containers on an
internal network and no published ports. It uses the same cached immutable
application images recorded in the
[previous acceptance](observability-acceptance-2026-10-22.md#successful-fixture).
No build/pull or provider/Telegram worker runs. Real issuer registration/login,
tenant creation and bot registration use only synthetic credentials and the
existing controlled Telegram setup boundary. AI jobs and webhook state fixtures
are inserted only into this new project's databases.

The relay runs as separate processes in the owned probe, scripts mounted
read-only. JWTs enter through stdin and child environment, never CLI argument
values, output or SQLite. Ownership is checked before SQL and lifecycle actions.
All new data and receipts remain under ignored `.venv` and owned Docker volumes.

Successful project: `nexus-events-ecaa1877207e44b0bfd5344e81197438`.
Driver exit 0; retained receipt has `passed=true`, `owned_stopped=true`,
`external_calls_enabled=false` and the source hash above.

| Check | Actual result |
| --- | --- |
| Initial observations | `auth.tenant.observed`, `webhook.bot.observed`, `ai.job.observed`; six accepted per-sink deliveries |
| Equal safe envelopes | All three types match EventPipe payload, authorized S3 raw bytes and PipeWatch metadata; names/messages/provider/model/token absent |
| Auth scope | Null bot ID, no EventPipe scalar bot metadata; creation time and caller role only |
| Repeat process | Still six accepted; three stored observations in each backend, no duplicates |
| Tenant isolation | Missing bearer 401; nonexistent tenant denied; authorized tenant B gets EventPipe event/raw 404 and zero PipeWatch logs; source bot A under B is 404 |
| Webhook change | Synthetic failed configuration produces one new version in each backend; eight accepted |
| Sink outage | Only owned ingest stopped; new failed job accepted by PipeWatch, EventPipe outcome unknown; nine accepted, one unknown |
| Sink recovery | Ingest healthy again; repeat retains nine accepted/one unknown, no automatic resend |
| Deactivation | Actual registry API 200; AI read 403/404; inactive bot snapshot reaches both sinks; eleven accepted/one unknown and source_errors=1 |
| Source outage | Only owned WebHook API stopped; Auth still authorizes its scan; source_errors=2, counters unchanged |
| Logout | Actual issuer logout 204; subsequent all-source failure returns static diagnostic and makes no further sink calls |
| Final storage | EventPipe five records, PipeWatch six; one deliberate unresolved EventPipe outcome |
| Stop | All fourteen stopped, no OOM, restart=no; twelve exit 0, Kafka/ZooKeeper exit 143 |

An earlier fresh attempt, `nexus-events-78abfe91339946db9e1fff748dacce6f`,
passed initial delivery/isolation but failed in private fixture preparation:
`webhook_status` is a computed model property, not a bot table column. The
corrected driver inserts a synthetic `telegram_bot_webhooks` row and updates
only its newly created bot timestamp. The failed receipt remains `passed=false`;
its fourteen containers stopped without OOM, with the same clean exit pattern.
No existing data was modified to repair the fixture.

## Verification commands and preservation

```powershell
& .venv/tooling-checks/Scripts/python.exe -B .venv/verify_identity_bots_20261022.py
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/capture_stack_smoke_root.py .venv/identity-bots-20261022-main-before.json
& ../WebHook_Manager/.venv/Scripts/python.exe -B .venv/capture_stack_smoke_root.py .venv/identity-bots-20261022-main-after.json
& .venv/tooling-checks/Scripts/python.exe -B .venv/check_identity_bots_preservation_20261022.py
& .venv/tooling-checks/Scripts/python.exe -B .venv/check_identity_bots_logs_20261022.py
```

The Docker driver and preservation helpers are local acceptance tools, not a
portable public test suite. The committed unit tests and CLI commands above
provide the repository's reproducible automated checks.

Read-only comparison preserved every original **580 container, 313 volume,
67 network, image and protected-file record**, including all **70 completed
scanner states**. Main database rows/schema/sequences/metadata, uploads and modes,
nine container definitions and `.env`/release/WSL hashes match before/after.
The separately saved main-before and main-after snapshots are equal.

Both attempts retain **28 new stopped containers, 20 new local named volumes
and two internal networks**. Final inventory: **608 containers, 333 volumes,
69 networks, 70 stopped scanners and only nine original running containers**.
No resource was deleted or original container restarted/recreated. Safe inventory
used `--size=false` and inspect batches of at most 100 IDs.
The bounded log scan of the successful fourteen-container fixture found no
Python traceback (at most 3,000 lines per container, captured without emitting
raw logs). Independent review covers the scoped relay, tests and trust boundaries.
Fresh read-only adversarial/security review: **APPROVE**, no confirmed defects or
security blockers. Reviewer independently reran the root/focused checks and
compared the saved preservation snapshots and successful receipt; it did not
rerun Docker or mutate the fixture.

## Limits

These are metadata snapshots, not global login/logout audit, complete membership
history or webhook ingress/delivery history. Polling can miss intermediate
changes. No existing root activation, production/off-host deployment, dashboard,
sustained load or real Telegram/LLM acceptance was performed. Owner JWT renewal
and explicit reconciliation of unknown deliveries remain operator work;
accepted receipts do not guarantee exactly-once backend storage.
