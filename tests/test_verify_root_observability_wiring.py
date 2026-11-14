"""Static gate for the opt-in root observability-events profile.

Parses `docker-compose.yml` and `.env.example`; starts nothing. The profile is
defined here but is not activated by the root stack. Runtime acceptance for
Stage 1 requires the EventPipe revision that carries the tenant-boundary
migrations and is recorded separately.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"
PROFILE = "observability-events"

PROFILE_SERVICES = {
    "zookeeper",
    "kafka",
    "kafka_init",
    "eventpipe_postgres",
    "seaweedfs",
    "seaweedfs_init",
    "eventpipe_migrate",
    "eventpipe_ingest",
    "eventpipe_transform",
    "eventpipe_query",
}


class RootObservabilityEventsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
        cls.volumes = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["volumes"]
        cls.networks = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["networks"]
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
        for name in PROFILE_SERVICES:
            self.assertIn(PROFILE, self.services[name].get("profiles") or [])

    def test_eventpipe_builds_from_the_sibling_repository(self) -> None:
        for name in (
            "eventpipe_migrate",
            "eventpipe_ingest",
            "eventpipe_transform",
            "eventpipe_query",
        ):
            build = self.services[name].get("build") or {}
            self.assertEqual(build.get("context"), "../EventPipe", name)
            self.assertTrue(str(build.get("dockerfile", "")).startswith("ingest_service/")
                            or str(build.get("dockerfile", "")).startswith("query_service/")
                            or str(build.get("dockerfile", "")).startswith("transform_service/"))

    def test_platform_modes_are_literal_and_metrics_are_off(self) -> None:
        for name, key in (
            ("eventpipe_ingest", "EVENTPIPE_PLATFORM_MODE"),
            ("eventpipe_query", "QUERY_PLATFORM_MODE"),
            ("eventpipe_transform", "TRANSFORM_PLATFORM_MODE"),
        ):
            self.assertEqual(self.env(name).get(key), "true")
        for name in ("eventpipe_ingest", "eventpipe_query", "eventpipe_transform"):
            self.assertEqual(self.env(name).get("METRICS_ENABLED"), "false")

    def test_ingest_and_query_authorize_against_auth_service(self) -> None:
        self.assertEqual(
            self.env("eventpipe_ingest").get("EVENTPIPE_AUTH_URL"),
            "http://auth_service:8000",
        )
        self.assertEqual(
            self.env("eventpipe_query").get("QUERY_AUTH_URL"),
            "http://auth_service:8000",
        )

    def test_ports_stay_on_loopback_and_use_the_28xxx_range(self) -> None:
        published = {}
        for name in PROFILE_SERVICES:
            for port in self.services[name].get("ports") or []:
                self.assertIsInstance(port, str)
                self.assertTrue(port.startswith("127.0.0.1:"), f"{name}: {port}")
                published[name] = port
        self.assertEqual(published["eventpipe_ingest"], "127.0.0.1:28013:8013")
        self.assertEqual(published["eventpipe_query"], "127.0.0.1:28020:8020")
        self.assertEqual(set(published), {"eventpipe_ingest", "eventpipe_query"})

    def test_infrastructure_is_dedicated_and_internal(self) -> None:
        network = self.networks["observability_events_net"]
        self.assertIs(network.get("internal"), True)
        for name in ("zookeeper", "kafka", "eventpipe_postgres", "seaweedfs",
                     "eventpipe_transform"):
            self.assertEqual(
                self.services[name].get("networks"), ["observability_events_net"], name
            )
        for name in ("eventpipe_postgres", "seaweedfs", "kafka"):
            for volume in self.services[name].get("volumes") or []:
                self.assertNotIn("nexus_postgres_data", str(volume))
                self.assertNotIn("nexus_redis_data", str(volume))
        self.assertIn("nexus_eventpipe_postgres_data", self.volumes)
        self.assertIn("nexus_eventpipe_seaweed_data", self.volumes)
        self.assertIn("nexus_kafka_data", self.volumes)

    def test_migration_is_a_one_shot_before_the_applications(self) -> None:
        migrate = self.services["eventpipe_migrate"]
        self.assertEqual(migrate.get("restart"), "no")
        self.assertEqual(migrate.get("command"), ["alembic", "upgrade", "head"])
        for name in ("eventpipe_ingest", "eventpipe_transform", "eventpipe_query"):
            depends = self.services[name].get("depends_on") or {}
            self.assertIn("kafka_init", depends, name)

    def test_env_example_has_placeholders_only(self) -> None:
        for key in (
            "EVENTPIPE_DB_PASSWORD",
            "EVENTPIPE_DATABASE_URL",
            "SEAWEEDFS_ACCESS_KEY",
            "SEAWEEDFS_SECRET_KEY",
        ):
            self.assertIn(key, self.env_example)
            self.assertEqual(self.env_example[key], "", key)

    def test_profile_variables_default_empty_for_default_commands(self) -> None:
        compose = COMPOSE.read_text(encoding="utf-8")
        for key in (
            "EVENTPIPE_DATABASE_URL",
            "SEAWEEDFS_ACCESS_KEY",
            "SEAWEEDFS_SECRET_KEY",
        ):
            self.assertIn(f"${{{key}:-}}", compose)
            self.assertNotIn(f"${{{key}:?", compose)

    def test_database_password_is_a_secret_and_urls_are_operator_supplied(self) -> None:
        postgres = self.services["eventpipe_postgres"]
        environment = postgres.get("environment") or {}
        self.assertEqual(
            environment.get("POSTGRES_PASSWORD_FILE"),
            "/run/secrets/eventpipe_db_password",
        )
        self.assertIn("eventpipe_db_password", postgres.get("secrets") or [])
        compose = COMPOSE.read_text(encoding="utf-8")
        self.assertNotIn("eventpipe:${", compose)
        for name in ("eventpipe_migrate", "eventpipe_transform", "eventpipe_query"):
            values = " ".join(str(value) for value in (self.env(name) or {}).values())
            self.assertIn("EVENTPIPE_DATABASE_URL", values, name)


if __name__ == "__main__":
    unittest.main()
