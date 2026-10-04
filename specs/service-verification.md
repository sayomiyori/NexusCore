# Service Verification Acceptance Scope

## Goal

Verify each existing service independently, fix reproduced failures, then integrate proven contracts into the NexusCore live demo for recruiters and developers.

## Constraints

- Preserve independent repositories and existing user changes.
- Use Python versions and checks specified by each repository's CI.
- Use isolated PostgreSQL/Redis resources for tests; never clean demo or production data.
- External OAuth, Telegram and LLM calls use boundary doubles in automated tests. Real-provider results require a separate explicit live check and must be reported separately.
- No commits, deployment, dependency-wide modernization or unrelated refactors are part of this phase.
- Tenant support is evaluated as implemented; adding the platform tenant model is a subsequent integration task.

## Acceptance gates per service

1. Existing tests execute successfully and missing critical failure paths are tested.
2. Repository lint and type-check commands pass; missing checks are reported.
3. PostgreSQL migrations upgrade on an empty disposable database, downgrade and upgrade again; model drift is checked.
4. Docker build succeeds without secrets, local virtual environments or Git history in the image.
5. A real HTTP flow passes through the built service and its real infrastructure.
6. Authentication, authorization, duplicates, expired/revoked state and external failures are tested where applicable.
7. Security findings and unverified behavior are recorded. A service with an unresolved critical auth failure is not marked ready.

## AuthFortress first checkpoint

Registration returns 200; login returns a token pair; `/api/v1/auth/me` returns the registered identity. Wrong credentials, missing/malformed/expired tokens and using a refresh token as access return 401. Refresh rotates tokens, rejects replay, and logout revokes the session. A normal user cannot access admin endpoints.

Later AuthFortress checkpoints cover the role hierarchy, block/revoke behavior, TOTP and one-use backup codes, OAuth state/provider failures, rate limits, audit and Prometheus metrics.

## Integration after service gates

Verify identity propagation, event contracts and tenant authorization before the Telegram → webhook → queue → AgentHub → Telegram scenario. Add observability, then the dashboard and deployment. EventPipe uses Kafka and MinIO; decide its actual integration responsibility from its verified contracts rather than assuming it is a Redis Streams component.
