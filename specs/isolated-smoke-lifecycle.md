# Isolated smoke lifecycle

Docker Desktop startup on 2026-10-14 revived 23 previously stopped synthetic
scanner containers from retained smoke projects. Their bounded restart policy
was still configured and their scanner cleanup exit code was 143. Data was not
deleted; only inspected, receipt-owned test scanners were stopped and changed to
`restart=no`. The main deployment remains outside fixture mutations.

During verification, scanners retain `init: true` and `on-failure:2`; automatic
restart checks remain mandatory. Before final cleanup, inspect ownership, image,
internal network, closed/synthetic credentials and entrypoint. Disable restart
only for those owned scanner IDs, then stop the project and prove both stopped
state and `restart=no`. Repeated cleanup accepts already disabled policies;
active verification still rejects a disabled or unapproved scanner policy.
Failed fixtures and normal mode must preserve foreign resources and all volumes.
Duplicate service instances fail closed before any cleanup mutation.

With fixture Redis stopped, restart the same legacy API container. Require a
different start time, live 200 and ready 503, retained PostgreSQL quota 429,
unchanged duplicate event ID and HMAC denial. Broker restoration and the real
scanner must deliver exactly two callbacks without repeats after scanner restart.

Verify Docker-boundary regressions, standalone and controlled-AI scanner modes,
Ruff/compilation, fresh read-only review and before/after main integrity.
Automated smoke must not restart shared Docker/WSL; inspect persisted policy.
An explicitly requested manual Docker Desktop restart must compare completed
scanner IDs/start times/finish times/restart counts, restore existing main
processes and verify data/configuration/WSL integrity. Record startup failures
and runtime metadata differences; do not reset Docker, delete data or change WSL.
IPC fix acceptance requires two consecutive native Desktop restarts with exit 0
and no external socket/directory cleanup or forced process termination. Verify
the signed supported Desktop release and compare main/scanner/data fingerprints;
distinguish Desktop settings schema migration from changing WSL configuration.
No real Telegram/LLM, main rollout, global cleanup or new dependency.
