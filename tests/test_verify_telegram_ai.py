"""Controlled AI fixtures keep real storage/issuer and refuse live HTTP effects."""

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from test_verify_stack import PROJECT, resolved_config

from scripts import verify_stack as smoke
from scripts import verify_telegram_ai as ai


def controlled_config():
    value = ai.ai_config(smoke.IMAGES)
    value["name"] = PROJECT
    value["networks"]["default"]["name"] = PROJECT + "_default"
    for key, volume in value["volumes"].items():
        volume["name"] = PROJECT + "_" + key
    for service in value["services"].values():
        service["networks"] = {"default": None}
        service["volumes"] = [{"type": "volume", "source": item.split(":")[0], "target": item.split(":")[1]}
                              if isinstance(item, str) else item for item in service.get("volumes", [])]
    return value


class ControlledAISmokeTests(unittest.TestCase):
    def test_controlled_fixture_requires_explicit_mode_and_fixed_synthetic_settings(self):
        good = controlled_config()
        smoke.validate_config(good, PROJECT, smoke.IMAGES, True)
        with self.assertRaises(ValueError):
            smoke.validate_config(good, PROJECT, smoke.IMAGES)
        smoke.validate_config(resolved_config(), PROJECT, smoke.IMAGES)
        changes = (
            lambda value: value["services"]["agent_worker"]["environment"].update(GROQ_API_KEY="live-like-key"),
            lambda value: value["services"]["agent_service"]["environment"].update(PLATFORM_TENANT_ENABLED="true"),
            lambda value: value["services"]["webhook_service"]["environment"].update(AGENTHUB_BASE_URL="http://127.0.0.1:8014"),
            lambda value: value["services"]["agent_publisher"]["environment"].update(WEBHOOK_INTERNAL_URL="http://host.docker.internal:8001"),
            lambda value: value["services"]["callback"]["volumes"][0].update(read_only=False),
            lambda value: value["volumes"]["postgres_data"].update(external=True),
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                changed = copy.deepcopy(good)
                change(changed)
                smoke.validate_config(changed, PROJECT, smoke.IMAGES, True)

    def test_boundary_rejects_root_live_redirect_and_credential_origins(self):
        for value in ("http://127.0.0.1:8000", "http://host.docker.internal:8000", "https://192.168.1.3:8000",
                      "http://169.254.169.254:8000", "http://user@192.168.1.3:8000", "http://192.168.1.3:8000?secret"):
            with self.subTest(value=value), patch.dict(os.environ, CONTROLLED_PROVIDER_URL=value), self.assertRaises(ValueError):
                ai.controlled_origin()
        with patch.dict(os.environ, CONTROLLED_PROVIDER_URL="http://192.168.1.3:8000"):
            self.assertEqual(ai.controlled_origin(), "http://192.168.1.3:8000")
        for value in ("https://api.telegram.org/synthetic", "http://127.0.0.1:28080", "http://auth_service:8001", "http://user@auth_service:8000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ai.internal_request(ai.httpx.Request("GET", value))
        ai.internal_request(ai.httpx.Request("GET", "http://auth_service:8000/health"))

    def test_controlled_receiver_refuses_invalid_model_and_counts_single_effect(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), ai.receiver_handler())
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        payload = {"model": "openai/gpt-oss-20b", "max_completion_tokens": 1024,
                   "messages": [{"role": "user", "content": "Synthetic question"}]}
        try:
            self.assertEqual(smoke.request(base + "/groq", "POST", {**payload, "tools": []})[0], 400)
            status, reply = smoke.request(base + "/groq", "POST", payload)
            self.assertEqual(status, 200)
            self.assertEqual(reply["usage"]["total_tokens"], 15)
            receipt = smoke.request(base + "/receipt")[1]
            self.assertEqual((receipt["groq"], receipt["send"], receipt["errors"]), (1, 0, 1))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_cleanup_failure_produces_failed_safe_receipt_without_running_legacy(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(ai.smoke, "Fixture") as boundary, \
                patch.object(ai, "verify", return_value={}), patch.object(ai.smoke, "main") as legacy, \
                contextlib.redirect_stdout(io.StringIO()):
            fixture = boundary.return_value
            fixture.project = PROJECT
            fixture.directory = Path(directory)
            fixture.images = smoke.IMAGES
            fixture.environment = {}
            fixture.proof.return_value = {}
            fixture.callback_origin = "http://192.168.1.3:8000"
            fixture.stop.side_effect = TimeoutError("secret-must-not-be-saved")
            with self.assertRaises(TimeoutError):
                ai.main([])
            receipt = json.loads((fixture.directory / "receipt.json").read_text())
            legacy.assert_not_called()
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["owned_containers_stopped"])
        self.assertNotIn("secret-must", json.dumps(receipt))

    def test_send_effect_requires_committed_processing_marker_and_installed_driver(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), ai.receiver_handler())
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        engine = MagicMock()
        result = engine.connect.return_value.__enter__.return_value.execute.return_value
        payload = {"chat_id": 17, "text": "Synthetic sender answer"}
        try:
            with patch.dict(os.environ, DATABASE_URL="postgresql+asyncpg://smoke:synthetic@postgres:5432/webhook_test"), \
                    patch("sqlalchemy.create_engine", return_value=engine) as database:
                for state in (("unknown", None), ("processing", None)):
                    result.one.return_value = state
                    self.assertEqual(smoke.request(base + "/send", "POST", payload)[0], 400)
                result.one.return_value = ("processing", object())
                self.assertEqual(smoke.request(base + "/send", "POST", payload)[0], 200)
                self.assertIn("postgresql+psycopg://", database.call_args.args[0])
                self.assertEqual(engine.dispose.call_count, 3)
            receipt = smoke.request(base + "/receipt")[1]
            self.assertEqual((receipt["send"], receipt["errors"]), (1, 2))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_optimized_cli_refuses_before_docker_or_database_access(self):
        result = subprocess.run([sys.executable, "-O", str(Path(ai.__file__).resolve()), "--help"],
                                capture_output=True, text=True, timeout=10, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STOP: VerificationError; details withheld", result.stderr)
        self.assertNotIn("RECEIPT", result.stdout)


if __name__ == "__main__":
    unittest.main()
