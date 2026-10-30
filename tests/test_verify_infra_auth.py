from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"
INIT = ROOT / "init-scripts" / "02-create-service-roles.sh"
PROVISION = ROOT / "scripts" / "provision-service-db-roles.sh"


class InfrastructureAuthTests(unittest.TestCase):
    def test_env_example_has_no_shared_runtime_passwords(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        for name in (
            "REDIS_PASSWORD=",
            "AUTH_DB_PASSWORD=",
            "WEBHOOK_DB_PASSWORD=",
            "AGENT_DB_PASSWORD=",
        ):
            self.assertIn(f"{name}\n", text)

    def test_compose_authenticates_redis_and_scopes_databases(self) -> None:
        text = COMPOSE.read_text(encoding="utf-8")
        redis = text[text.index("  redis:") : text.index("  auth_service:")]
        self.assertIn("--requirepass", redis)
        self.assertIn("REDISCLI_AUTH", redis)
        postgres = text[text.index("  postgres:") : text.index("  redis:")]
        for name in (
            "AUTH_DB_PASSWORD",
            "WEBHOOK_DB_PASSWORD",
            "AGENT_DB_PASSWORD",
        ):
            self.assertIn(f"{name}: ${{", postgres)
        self.assertIn(
            "postgresql+psycopg2://auth_service:${AUTH_DB_PASSWORD:?Set AUTH_DB_PASSWORD}@postgres:5432/authfortress",
            text,
        )
        self.assertIn(
            "postgresql+asyncpg://webhook_service:${WEBHOOK_DB_PASSWORD:?Set WEBHOOK_DB_PASSWORD}@postgres:5432/webhook_manager",
            text,
        )
        self.assertIn(
            "postgresql+psycopg://agent_service:${AGENT_DB_PASSWORD:?Set AGENT_DB_PASSWORD}@postgres:5432/agenthub",
            text,
        )
        for line in text.splitlines():
            if line.strip().startswith(("REDIS_URL:", "CELERY_BROKER_URL:")):
                self.assertIn("${REDIS_PASSWORD", line)
            if line.strip().startswith("DATABASE_URL:"):
                self.assertNotIn("${POSTGRES_USER", line)

    def test_role_provisioning_scripts_revoke_public_connect(self) -> None:
        for path in (INIT, PROVISION):
            text = path.read_text(encoding="utf-8")
            self.assertIn("REVOKE CONNECT", text)
            self.assertIn("ALTER DATABASE", text)
            self.assertNotIn(b"\r", path.read_bytes())
        fresh = INIT.read_text(encoding="utf-8")
        for role in ("auth_service", "webhook_service", "agent_service"):
            self.assertIn(f"CREATE ROLE {role}", fresh)
        provision = PROVISION.read_text(encoding="utf-8")
        for statement in (
            "CREATE EXTENSION IF NOT EXISTS vector",
            "ALTER TYPE",
            "ALTER VIEW",
            "ALTER MATERIALIZED VIEW",
            "ALTER FUNCTION",
            "deptype = 'e'",
        ):
            self.assertIn(statement, provision)


if __name__ == "__main__":
    unittest.main()
