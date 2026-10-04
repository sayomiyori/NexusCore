# Git working-tree snapshot — 2026-10-03

Uncommitted state retained at the user-requested pause. Paths only; no secrets or file contents.

## NexusCore

```text
?? .env
?? .env.example
?? AGENTS.md
?? PROJECT-MAP.md
?? docker-compose.yml
?? docs/
?? init-scripts/
?? specs/
```

## AuthFortress

```text
 M .env.example
 M Dockerfile
 M app/api/v1/auth.py
 M app/api/v1/oauth.py
 M app/config.py
 M app/core/rate_limiter.py
 M app/services/oauth/base.py
 M app/services/oauth/github.py
 M app/services/oauth/google.py
 M app/services/oauth/yandex.py
 M requirements.txt
 M tests/test_oauth.py
 M tests/test_twofa.py
?? scripts/verify_twofa_concurrency.py
?? tests/test_config.py
?? tests/test_oauth_http.py
?? tests/test_oauth_providers.py
?? tests/test_rate_limiter.py
```

## WebHook_Manager

```text
 M .github/workflows/ci.yml
 M docker-compose.yml
 M src/api/v1/dependencies/auth.py
 M src/api/v1/routers/deliveries.py
 M src/api/v1/routers/endpoints.py
 M src/api/v1/routers/events.py
 M src/api/v1/routers/ingest.py
 M src/api/v1/routers/subscriptions.py
 M src/core/security.py
 M src/infrastructure/db/repositories/source_repository.py
 M src/infrastructure/queue/celery_app.py
 M src/infrastructure/queue/tasks/deliver_webhook.py
 M tests/conftest.py
 M tests/e2e/test_api_crud.py
 M tests/e2e/test_webhook_flow.py
 M tests/unit/test_hmac.py
?? .cursor/
?? .dockerignore
?? docs/ERRORS.md
?? docs/verification-checkpoint.md
?? docs/verification.compose.yml
?? scripts/verify_http.py
?? tests/e2e/test_management_authorization.py
?? tests/integration/test_worker_delivery.py
```

## AgentHub

```text
 M .env.example
 M .github/workflows/ci.yml
 M app/config.py
 M app/services/llm/factory.py
 M app/services/llm/pricing.py
 M app/services/rag_pipeline.py
 M app/workers/embed_worker.py
 M docker-compose.yml
 M requirements.txt
?? .dockerignore
?? app/services/llm/groq.py
?? docker-compose.verification.yml
?? docs/ERRORS.md
?? docs/verification-checkpoint.md
?? tests/http_smoke.py
?? tests/test_infrastructure.py
?? tests/verification_app.py
```

## EventPipe

```text
 M query_service/app/api/events.py
 M transform_service/app/consumer.py
 M transform_service/tests/test_integration_transform.py
?? .dockerignore
?? docker-compose.test.yml
?? docs/dependency-audit.json
?? scripts/
?? transform_service/tests/test_consumer_failures.py
```

## PipeWatch

```text
 M app/main.py
 M app/services/clickhouse.py
 D "docs/images/dc ps.png"
 M tests/test_ingest_query_verify.py
?? .dockerignore
?? docker-compose.test.yml
?? docs/images/docker-services.png
?? tests/test_clickhouse_boundaries.py
?? tests/test_flush_failure.py
```
