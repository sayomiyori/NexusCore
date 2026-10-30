from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"

API_SERVICES = {"auth_service", "webhook_service", "agent_service"}


class RuntimeHardeningTests(unittest.TestCase):
    def test_postgres_credentials_are_required(self) -> None:
        env = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("POSTGRES_USER=\n", env)
        self.assertIn("POSTGRES_PASSWORD=\n", env)
        compose = COMPOSE.read_text(encoding="utf-8")
        self.assertIn("${POSTGRES_USER:?Set POSTGRES_USER}", compose)
        self.assertIn("${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}", compose)

    def test_every_service_gets_bounded_json_file_logs(self) -> None:
        data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
        shared = data["x-default-logging"]
        self.assertEqual(shared["driver"], "json-file")
        self.assertEqual(shared["options"], {"max-size": "10m", "max-file": "3"})
        services = data["services"]
        self.assertEqual(len(services), 15)
        for name, service in services.items():
            self.assertEqual(
                service.get("logging"),
                shared,
                f"{name} is missing the shared logging block",
            )

    def test_only_api_services_are_read_only_and_capability_free(self) -> None:
        data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
        hardened = {
            name
            for name, service in data["services"].items()
            if service.get("read_only") is True
        }
        self.assertEqual(hardened, API_SERVICES)
        for name in API_SERVICES:
            service = data["services"][name]
            self.assertEqual(service["cap_drop"], ["ALL"], name)
            self.assertEqual(service["tmpfs"], ["/tmp"], name)
            self.assertEqual(service["pids_limit"], 256, name)
            self.assertIn("no-new-privileges:true", service["security_opt"], name)


if __name__ == "__main__":
    unittest.main()
