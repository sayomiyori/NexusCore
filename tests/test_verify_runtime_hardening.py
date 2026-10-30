from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"

API_SERVICES = {"auth_service", "webhook_service", "agent_service"}
SERVICES = {
    "postgres",
    "redis",
    "auth_service",
    "webhook_service",
    "webhook_worker",
    "webhook_delivery_recovery",
    "webhook_outbox_recovery",
    "agent_service",
    "agent_worker",
    "agent_telegram_worker",
    "agent_telegram_recovery",
    "agent_reply_worker",
    "agent_reply_recovery",
    "webhook_sender",
    "webhook_send_recovery",
}
SERVICE_HEADER = re.compile(r"^  ([a-z][a-z0-9_]*):$", re.MULTILINE)


def blocks(text: str) -> dict[str, str]:
    """Split the `services:` section into per-service text blocks.

    Avoids a YAML dependency: the checks are about which anchors each service
    carries, which the file already expresses as text.
    """
    start = text.index("\nservices:\n") + len("\nservices:\n")
    section = text[start:]
    markers = list(SERVICE_HEADER.finditer(section))
    parsed: dict[str, str] = {}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(section)
        parsed[marker.group(1)] = section[marker.start() : end]
    return parsed


class RuntimeHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = COMPOSE.read_text(encoding="utf-8")
        cls.services = blocks(cls.text)

    def test_postgres_credentials_are_required(self) -> None:
        env = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("POSTGRES_USER=\n", env)
        self.assertIn("POSTGRES_PASSWORD=\n", env)
        self.assertIn("${POSTGRES_USER:?Set POSTGRES_USER}", self.text)
        self.assertIn("${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}", self.text)

    def test_shared_logging_anchor_is_bounded(self) -> None:
        anchor = self.text[self.text.index("x-default-logging:") :]
        anchor = anchor[: anchor.index("x-api-hardening:")]
        self.assertIn("driver: json-file", anchor)
        self.assertIn('max-size: "10m"', anchor)
        self.assertIn('max-file: "3"', anchor)

    def test_every_service_gets_the_shared_logging_block(self) -> None:
        self.assertEqual(set(self.services), SERVICES)
        for name, block in self.services.items():
            self.assertIn(
                "logging: *default_logging",
                block,
                f"{name} is missing the shared logging block",
            )

    def test_only_api_services_are_read_only_and_capability_free(self) -> None:
        anchor = self.text[self.text.index("x-api-hardening:") :]
        anchor = anchor[: anchor.index("\nservices:\n")]
        self.assertIn("read_only: true", anchor)
        self.assertIn('cap_drop: ["ALL"]', anchor)
        self.assertIn('tmpfs: ["/tmp"]', anchor)
        self.assertIn("pids_limit: 256", anchor)
        hardened = {
            name
            for name, block in self.services.items()
            if "<<: *api_hardening" in block
        }
        self.assertEqual(hardened, API_SERVICES)
        for name in API_SERVICES:
            self.assertIn(
                'security_opt: ["no-new-privileges:true"]',
                self.services[name],
                name,
            )
        for name, block in self.services.items():
            if name in API_SERVICES:
                continue
            self.assertNotIn("read_only", block, name)
            self.assertNotIn("cap_drop", block, name)


if __name__ == "__main__":
    unittest.main()
