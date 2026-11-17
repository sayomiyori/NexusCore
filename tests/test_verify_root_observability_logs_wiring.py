"""Static gate for the opt-in root observability-logs profile.

Parses `docker-compose.yml` and `.env.example`; starts nothing. PipeWatch and
its ClickHouse/Redis are defined but never activated by the default stack.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"
PROFILE = "observability-logs"

PROFILE_SERVICES = {"pipewatch_clickhouse", "pipewatch_redis", "pipewatch"}


class RootObservabilityLogsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        parsed = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
        cls.services = parsed["services"]
        cls.volumes = parsed["volumes"]
        cls.networks = parsed["networks"]
        cls.env_example = {}
        for raw in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                cls.env_example[key.strip()] = value.strip()

    def env(self, service: str) -> dict[str, object]:
        return self.services[service].get("environment") or {}

    def test_profile_holds_exactly_the_documented_services(self) -> None:
        in_profile = {
            name
            for name, service in self.services.items()
            if PROFILE in (service.get("profiles") or [])
        }
        self.assertEqual(in_profile, PROFILE_SERVICES)

    def test_pipewatch_builds_from_the_sibling_repository(self) -> None:
        build = self.services["pipewatch"].get("build") or {}
        self.assertEqual(build.get("context"), "../PipeWatch")

    def test_pipewatch_platform_contract_is_literal(self) -> None:
        env = self.env("pipewatch")
        self.assertEqual(env.get("PLATFORM_AUTH_ENABLED"), "true")
        self.assertEqual(env.get("AUTHFORTRESS_URL"), "http://auth_service:8000")
        self.assertEqual(env.get("METRICS_ENABLED"), "false")
        self.assertEqual(env.get("TELEGRAM_NOTIFICATIONS_ENABLED"), "false")
        self.assertEqual(env.get("TELEGRAM_BOT_TOKEN"), "")
        self.assertEqual(env.get("TELEGRAM_CHAT_ID"), "")

    def test_pipewatch_is_the_only_published_service(self) -> None:
        published = {
            name: service.get("ports")
            for name, service in self.services.items()
            if service.get("ports")
        }
        self.assertEqual(
            published["pipewatch"], ["127.0.0.1:28084:8000"]
        )
        self.assertNotIn("pipewatch_clickhouse", published)
        self.assertNotIn("pipewatch_redis", published)

    def test_redis_is_durable_without_eviction(self) -> None:
        command = self.services["pipewatch_redis"].get("command") or []
        self.assertIn("--appendonly", command)
        self.assertEqual(command[command.index("--appendonly") + 1], "yes")
        self.assertIn("--appendfsync", command)
        self.assertEqual(command[command.index("--appendfsync") + 1], "always")
        self.assertIn("--maxmemory-policy", command)
        self.assertEqual(command[command.index("--maxmemory-policy") + 1], "noeviction")

    def test_infrastructure_is_dedicated_and_internal(self) -> None:
        network = self.networks["observability_logs_net"]
        self.assertIs(network.get("internal"), True)
        for name in ("pipewatch_clickhouse", "pipewatch_redis"):
            self.assertEqual(
                self.services[name].get("networks"), ["observability_logs_net"], name
            )
        self.assertEqual(
            self.services["pipewatch"].get("networks"),
            ["nexus_net", "observability_logs_net"],
        )
        self.assertIn("nexus_pipewatch_clickhouse_data", self.volumes)
        self.assertIn("nexus_pipewatch_redis_data", self.volumes)
        for name in ("pipewatch_clickhouse", "pipewatch_redis"):
            for volume in self.services[name].get("volumes") or []:
                self.assertNotIn("nexus_postgres_data", str(volume))
                self.assertNotIn("nexus_redis_data", str(volume))

    def test_env_example_has_the_clickhouse_placeholder(self) -> None:
        self.assertIn("PIPEWATCH_CLICKHOUSE_PASSWORD", self.env_example)
        self.assertEqual(self.env_example["PIPEWATCH_CLICKHOUSE_PASSWORD"], "")
        self.assertNotIn("PIPEWATCH_REDIS_PASSWORD", self.env_example)

    def test_images_are_digest_pinned(self) -> None:
        for name in ("pipewatch_clickhouse", "pipewatch_redis"):
            image = str(self.services[name].get("image", ""))
            self.assertIn("@sha256:", image, name)


if __name__ == "__main__":
    unittest.main()
