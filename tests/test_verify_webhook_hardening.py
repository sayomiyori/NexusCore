from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
SPEC = ROOT / "specs" / "legacy-auth-hardening.md"


class LegacyWebhookHardeningTests(unittest.TestCase):
    def test_webhook_cors_and_hosts_are_restricted(self) -> None:
        text = COMPOSE.read_text(encoding="utf-8")
        start = text.index("  webhook_service:")
        end = text.index("  webhook_worker:", start)
        service = text[start:end]
        cors = re.search(r"CORS_ORIGINS: '(.+)'", service)
        hosts = re.search(r"TRUSTED_HOSTS: '(.+)'", service)
        self.assertIsNotNone(cors)
        self.assertIsNotNone(hosts)
        self.assertEqual(json.loads(cors.group(1)), ["http://127.0.0.1:3000"])
        self.assertEqual(
            set(json.loads(hosts.group(1))),
            {"127.0.0.1", "localhost", "webhook_service"},
        )
        self.assertIn("--no-proxy-headers", service)
        self.assertIn("alembic upgrade head", service)

    def test_spec_records_legacy_limits_and_residuals(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        self.assertIn("at least 6 characters", text)
        self.assertIn("72 UTF-8 bytes", text)
        self.assertIn("60", text)
        self.assertIn("Residuals", text)


if __name__ == "__main__":
    unittest.main()
