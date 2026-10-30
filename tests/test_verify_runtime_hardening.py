from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"


class RuntimeHardeningTests(unittest.TestCase):
    def test_postgres_credentials_are_required_and_hardened(self) -> None:
        env = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("POSTGRES_USER=\n", env)
        self.assertIn("POSTGRES_PASSWORD=\n", env)
        compose = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("${POSTGRES_USER:?Set POSTGRES_USER}", compose)
        self.assertIn("${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}", compose)
        for name, following in (
            ("auth_service", "webhook_service"),
            ("webhook_service", "webhook_worker"),
            ("agent_service", "agent_worker"),
        ):
            start = compose.index(f"  {name}:")
            end = compose.index(f"  {following}:", start)
            self.assertIn(
                'security_opt: ["no-new-privileges:true"]',
                compose[start:end],
            )


if __name__ == "__main__":
    unittest.main()
