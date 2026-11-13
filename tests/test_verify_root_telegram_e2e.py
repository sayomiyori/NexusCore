"""Unit checks for the root-derived fixture in verify_root_telegram_e2e."""

from __future__ import annotations

import unittest

from scripts import verify_root_telegram_e2e as e2e
from scripts import verify_stack as smoke


def _base() -> dict:
    services = {}
    for fixture_name in e2e.MAPPING:
        services[fixture_name] = {
            "environment": {
                "DATABASE_URL": "postgresql+fixture://fixture/db",
                "BOT_CREDENTIALS_KEY": "${AI_BOT_KEY}",
                "PLATFORM_BOTS_ENABLED": "true",
                "AUTHFORTRESS_BASE_URL": "http://auth_service:8000",
            }
        }
    services["postgres"] = {"environment": {"POSTGRES_USER": "smoke"}}
    return {"services": services}


def _rendered() -> dict:
    services = {}
    for root_name in e2e.MAPPING.values():
        services[root_name] = {
            "environment": {
                "DATABASE_URL": "postgresql+root://root/prod",
                "BOT_CREDENTIALS_KEY": "",
                "PLATFORM_BOTS_ENABLED": "false",
                "AUTHFORTRESS_BASE_URL": "http://auth_service:8000",
                "LLM_PROVIDER": "groq",
            }
        }
    return {"services": services}


class RootTelegramDerivationTests(unittest.TestCase):
    def test_merge_keeps_fixture_storage_and_synthetic_secrets(self) -> None:
        merged = e2e.merge_service(
            _base()["services"]["webhook_service"]["environment"],
            _rendered()["services"]["webhook_service"]["environment"],
        )
        self.assertEqual(merged["DATABASE_URL"], "postgresql+fixture://fixture/db")
        self.assertEqual(merged["BOT_CREDENTIALS_KEY"], "${AI_BOT_KEY}")
        self.assertEqual(merged["PLATFORM_BOTS_ENABLED"], "true")
        self.assertEqual(merged["LLM_PROVIDER"], "groq")
        self.assertEqual(merged["AUTHFORTRESS_BASE_URL"], "http://auth_service:8000")

    def test_derive_maps_every_fixture_service(self) -> None:
        derived = e2e.derive_config(_base(), _rendered())
        for fixture_name, root_name in e2e.MAPPING.items():
            self.assertIn(fixture_name, derived["services"])
            merged = derived["services"][fixture_name]["environment"]
            self.assertEqual(merged["LLM_PROVIDER"], "groq")
            self.assertNotIn(
                "root", merged["DATABASE_URL"], f"{fixture_name} kept the root database"
            )
            self.assertIn(root_name, _rendered()["services"])

    def test_missing_root_service_fails_closed(self) -> None:
        rendered = _rendered()
        rendered["services"].pop("agent_telegram_worker")
        with self.assertRaises(smoke.VerificationError):
            e2e.derive_config(_base(), rendered)

    def test_wiring_drift_fails_closed(self) -> None:
        derived = e2e.derive_config(_base(), _rendered())
        e2e.assert_wiring(derived, _rendered())
        derived["services"]["agent_service"]["environment"]["LLM_PROVIDER"] = "other"
        with self.assertRaises(smoke.VerificationError):
            e2e.assert_wiring(derived, _rendered())


if __name__ == "__main__":
    unittest.main()
