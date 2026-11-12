"""Static regression gate for the root Telegram platform wiring.

Parses ``docker-compose.yml`` and ``.env.example`` directly; no Docker engine,
no service start, no live Telegram or provider call.

The gate encodes security invariants, not prose. Two places where the approved
specification is narrower than the reviewed stack are recorded explicitly:

* ``webhook_send_recovery`` also holds ``BOT_CREDENTIALS_KEY``: it recovers and
  sends answers, so it decrypts bot tokens like ``webhook_sender``.
* recovery processes keep ``TELEGRAM_AI_MODEL``/``LLM_PROVIDER`` because they
  re-claim frozen jobs, but their ``GROQ_API_KEY`` is empty.

If this file starts failing after a wiring change, fix the wiring in a separate
reviewed change; do not relax an assertion to make the gate green.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"

DEFAULT_FALSE_FLAGS = (
    "PLATFORM_BOTS_ENABLED",
    "PLATFORM_TELEGRAM_ENABLED",
    "TELEGRAM_AI_ENABLED",
    "TELEGRAM_REPLIES_ENABLED",
    "PLATFORM_READ_ENABLED",
)

AGENT_GENERATION = {
    "agent_service",
    "agent_telegram_worker",
    "agent_telegram_recovery",
    "agent_reply_worker",
    "agent_reply_recovery",
}


class RootTelegramWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        parsed = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
        cls.services: dict[str, dict] = parsed["services"]
        cls.env_example = cls._read_env_example()

    @staticmethod
    def _read_env_example() -> dict[str, str]:
        values: dict[str, str] = {}
        for raw in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        return values

    def env(self, service: str) -> dict[str, object]:
        return self.services[service].get("environment") or {}

    def services_with(self, key: str) -> set[str]:
        return {name for name in self.services if key in self.env(name)}

    def test_platform_flags_default_false(self) -> None:
        for flag in DEFAULT_FALSE_FLAGS:
            with self.subTest(flag=flag):
                self.assertEqual(self.env_example.get(flag), "false")
                for name in self.services:
                    value = self.env(name).get(flag)
                    if value is None:
                        continue
                    self.assertIn(
                        value,
                        ("false", f"${{{flag}:-false}}"),
                        f"{name} must default {flag} to false",
                    )

    def test_tenant_isolation_defaults_true(self) -> None:
        for name in ("agent_service", "agent_telegram_worker"):
            self.assertEqual(
                self.env(name).get("PLATFORM_TENANT_ENABLED"),
                "${PLATFORM_TENANT_ENABLED:-true}",
            )

    def test_bot_credentials_stay_out_of_agent_processes(self) -> None:
        holders = self.services_with("BOT_CREDENTIALS_KEY")
        self.assertEqual(
            holders,
            {"webhook_service", "webhook_sender", "webhook_send_recovery"},
        )
        self.assertFalse(any(name.startswith("agent_") for name in holders))

    def test_recovery_processes_have_no_provider_credential(self) -> None:
        for name in sorted(self.services):
            if name.startswith("agent_") and name.endswith("_recovery"):
                value = self.env(name).get("GROQ_API_KEY")
                self.assertEqual(
                    "" if value is None else str(value),
                    "",
                    f"{name} must not receive GROQ_API_KEY",
                )

    def test_telegram_model_reaches_only_generation_processes(self) -> None:
        for key in ("TELEGRAM_AI_MODEL", "TELEGRAM_AI_PROVIDER"):
            self.assertLessEqual(self.services_with(key), AGENT_GENERATION)
        self.assertLessEqual(
            self.services_with("LLM_PROVIDER"), AGENT_GENERATION | {"agent_worker"}
        )

    def test_pairwise_hop_keys(self) -> None:
        ingress = self.services_with("WEBHOOK_AGENT_INGRESS_KEY")
        self.assertLessEqual(
            {"webhook_worker", "webhook_outbox_recovery", "agent_service"}, ingress
        )
        self.assertLessEqual(ingress, set(self.services) - {"postgres", "redis"})

        self.assertEqual(
            self.services_with("WEBHOOK_AGENT_CONTEXT_KEY"),
            {"webhook_service", "webhook_sender", "webhook_send_recovery"},
        )
        self.assertEqual(
            self.services_with("WEBHOOK_AGENT_SERVICE_KEY"),
            {
                "agent_service",
                "agent_telegram_worker",
                "agent_telegram_recovery",
                "agent_reply_worker",
                "agent_reply_recovery",
            },
        )
        self.assertEqual(
            self.services_with("AGENT_WEBHOOK_REPLY_KEY"),
            {
                "webhook_service",
                "webhook_sender",
                "webhook_send_recovery",
                "agent_service",
                "agent_telegram_worker",
                "agent_telegram_recovery",
                "agent_reply_worker",
                "agent_reply_recovery",
            },
        )
        self.assertEqual(
            self.services_with("AUTHFORTRESS_WEBHOOK_SERVICE_KEY"),
            {
                "auth_service",
                "webhook_service",
                "webhook_worker",
                "webhook_outbox_recovery",
                "webhook_sender",
                "webhook_send_recovery",
            },
        )

    def test_telegram_origin_reaches_only_webhook_senders(self) -> None:
        self.assertEqual(
            self.services_with("TELEGRAM_WEBHOOK_ORIGIN"),
            {"webhook_service", "webhook_sender", "webhook_send_recovery"},
        )

    def test_workers_keep_route_serving_flags_off(self) -> None:
        for name in (
            "webhook_worker",
            "webhook_outbox_recovery",
            "webhook_delivery_recovery",
        ):
            with self.subTest(service=name):
                self.assertEqual(self.env(name).get("PLATFORM_BOTS_ENABLED"), "false")
                self.assertEqual(
                    self.env(name).get("PLATFORM_TELEGRAM_ENABLED"), "false"
                )

    def test_profiles_contain_exactly_the_documented_services(self) -> None:
        def in_profile(profile: str) -> set[str]:
            return {
                name
                for name in self.services
                if profile in (self.services[name].get("profiles") or [])
            }

        self.assertEqual(in_profile("telegram-ingress"), {"webhook_outbox_recovery"})
        self.assertEqual(
            in_profile("telegram-ai"),
            {
                "webhook_outbox_recovery",
                "agent_telegram_worker",
                "agent_telegram_recovery",
                "agent_reply_worker",
                "agent_reply_recovery",
                "webhook_sender",
                "webhook_send_recovery",
            },
        )
        self.assertEqual(
            in_profile("legacy-recovery"), {"webhook_delivery_recovery"}
        )

    def test_published_ports_bind_loopback_only(self) -> None:
        for name in self.services:
            for port in self.services[name].get("ports") or []:
                self.assertIsInstance(port, str)
                self.assertTrue(
                    port.startswith("127.0.0.1:"),
                    f"{name} publishes {port} outside loopback",
                )

    def test_agent_service_keeps_preflight_and_healthcheck(self) -> None:
        service = self.services["agent_service"]
        self.assertIn("agent_platform_preflight.py", str(service.get("command")))
        self.assertEqual(
            service["healthcheck"]["test"],
            ["CMD", "python", "/app/agent_platform_healthcheck.py"],
        )


if __name__ == "__main__":
    unittest.main()
