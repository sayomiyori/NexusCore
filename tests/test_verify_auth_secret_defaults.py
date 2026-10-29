from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / ".env.example"
COMPOSE = ROOT / "docker-compose.yml"
PLACEHOLDERS = {
    "change-me-in-production-use-long-random",
    "replace_with_random_secret_at_least_32_characters",
}


class AuthSecretDefaultTests(unittest.TestCase):
    def test_example_has_no_usable_signing_secret(self) -> None:
        lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        values = {}
        for line in lines:
            if line.startswith(("AUTH_SECRET_KEY=", "WEBHOOK_SECRET_KEY=")):
                name, value = line.split("=", 1)
                values[name] = value
        self.assertEqual(
            values, {"AUTH_SECRET_KEY": "", "WEBHOOK_SECRET_KEY": ""}
        )
        self.assertTrue(PLACEHOLDERS.isdisjoint(values.values()))

    def test_compose_requires_both_signing_secrets(self) -> None:
        text = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("${AUTH_SECRET_KEY:?Set AUTH_SECRET_KEY}", text)
        self.assertIn("${WEBHOOK_SECRET_KEY:?Set WEBHOOK_SECRET_KEY}", text)

    def test_auth_service_does_not_trust_forwarded_headers(self) -> None:
        text = COMPOSE.read_text(encoding="utf-8")
        start = text.index("  auth_service:")
        end = text.index("  webhook_service:", start)
        self.assertIn("--no-proxy-headers", text[start:end])


if __name__ == "__main__":
    unittest.main()
