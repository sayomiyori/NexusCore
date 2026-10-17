# Standalone verification checks

Root verification tests must run from a fresh NexusCore checkout without sibling
repositories, application credentials, Docker or a running service. This closes
the existing reliance on WebHook Manager's local virtualenv.

Use Python 3.12 and the already tested verification dependencies, pinned in
`requirements-checks.txt`. These are development-only dependencies, not service
runtime requirements. Assume GitHub-hosted Ubuntu and Windows runners are
available; main deployment and WSL changes remain outside scope.

GitHub Actions runs unittest discovery, Ruff and compilation on relevant pushes,
pull requests and manual dispatch. Use read-only contents permission, immutable
official action revisions, no persisted checkout credentials and an 8-minute
job timeout. No service containers, secrets or real provider calls are needed.

Acceptance: install and run the commands in a clean local venv; `pip check`
passes; after publishing, both hosted operating-system jobs pass. Document the
same local commands and state that these are boundary regressions, not a full
Docker/service acceptance. No new test framework or application dependency.
