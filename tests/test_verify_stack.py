"""Smoke isolation/HTTP boundary regressions; Docker is replaced at its CLI boundary."""

import contextlib
import copy
import hashlib
import hmac
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts import verify_stack as smoke

PROJECT = "nexus-smoke-" + "a" * 32


def resolved_config():
    config = smoke.smoke_config(smoke.IMAGES)
    config["name"] = PROJECT
    config["networks"]["default"]["name"] = PROJECT + "_default"
    for key, volume in config["volumes"].items():
        volume["name"] = PROJECT + "_" + key
    for service in config["services"].values():
        service["networks"] = {"default": None}
        service["volumes"] = [
            {"type": "volume", "source": value.split(":")[0], "target": value.split(":")[1]}
            if isinstance(value, str) else value for value in service.get("volumes", [])]
    return config


class StackSmokeTests(unittest.TestCase):
    def test_internal_transport_rejects_root_and_uninspected_targets_before_exec(self):
        fixture = object.__new__(smoke.Fixture)
        fixture.addresses = ["192.168.48.4"]
        with patch.object(fixture, "compose") as docker:
            for url in ("http://127.0.0.1:28080/health", "http://192.168.48.5:8000/health",
                        "http://192.168.48.4:5432/health", "http://synthetic@192.168.48.4:8000/health"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    fixture.http(url)
            docker.assert_not_called()

    def test_private_http_requires_exact_inspected_allowlist_and_disables_proxy_redirect(self):
        response = Mock(status=200)
        response.read.return_value = b'{"status":"ok"}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(smoke, "build_opener", return_value=opener) as boundary:
            result = smoke.request("http://192.168.48.4:8000/health", allowed_addresses=["192.168.48.4"])
            self.assertEqual(result, (200, {"status": "ok"}))
            self.assertEqual(boundary.call_args.args[0].proxies, {})
            self.assertIsInstance(boundary.call_args.args[1], smoke.NoRedirect)
            with self.assertRaises(ValueError):
                smoke.request("http://192.168.48.5:8000/health", allowed_addresses=["192.168.48.4"])
            self.assertEqual(opener.open.call_count, 1)

    def test_fixture_closes_mcp_before_invoking_standalone_handler(self):
        app = FastAPI()
        invoked = []

        @app.get("/mcp/sse")
        def mcp():
            invoked.append(True)
            return {"unexpected": True}

        @app.get("/health")
        def health():
            return {"status": "ok"}

        module = types.ModuleType("app.main")
        module.app = app
        with patch.dict(sys.modules, {"app.main": module}):
            client = TestClient(smoke.create_agent_app())
            for path in ("/mcp", "/mcp/sse", "/mcp/messages/"):
                self.assertEqual(client.get(path).status_code, 404)
            self.assertEqual(client.get("/health").status_code, 200)
        self.assertEqual(invoked, [])

    def test_cleanup_failure_cannot_leave_a_successful_receipt(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(smoke, "Fixture") as boundary, \
                patch.object(smoke, "verify", return_value={}), contextlib.redirect_stdout(io.StringIO()):
            fixture = boundary.return_value
            fixture.project = PROJECT
            fixture.directory = Path(directory)
            fixture.images = smoke.IMAGES
            fixture.proof.return_value = {}
            fixture.callback_origin = "http://192.168.0.4:8000"
            fixture.stop.side_effect = TimeoutError("synthetic-details-must-not-be-saved")
            with self.assertRaises(TimeoutError):
                smoke.main([])
            receipt = json.loads((fixture.directory / "receipt.json").read_text())
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["owned_containers_stopped"])
        self.assertEqual(receipt["cleanup_error_class"], "TimeoutError")
        self.assertNotIn("synthetic-details", json.dumps(receipt))

    def test_root_network_storage_ports_and_live_settings_are_rejected(self):
        good = resolved_config()
        smoke.validate_config(good, PROJECT, smoke.IMAGES)
        changes = (
            lambda data: data.update(name="nexuscore"),
            lambda data: data["networks"]["default"].update(internal=False),
            lambda data: data["volumes"]["uploads"].update(name="nexuscore_nexus_agent_uploads"),
            lambda data: data["volumes"]["uploads"].update(external=True),
            lambda data: data["volumes"]["uploads"].update(driver_opts={"type": "none", "o": "bind", "device": "/existing-root-uploads"}),
            lambda data: data["services"]["agent_service"].update(ports=[{"host_ip": "127.0.0.1", "published": "8014", "target": 8000}]),
            lambda data: data["services"]["auth_service"].update(container_name="nexus-auth"),
            lambda data: data["services"]["webhook_service"]["environment"].update(PLATFORM_BOTS_ENABLED="true"),
            lambda data: data["services"]["agent_service"]["environment"].update(GROQ_API_KEY="synthetic-must-be-rejected"),
            lambda data: data["services"]["agent_service"]["environment"].update(DATABASE_URL="postgresql://127.0.0.1:25432/agenthub"),
            lambda data: data["services"]["agent_worker"]["environment"].update(CELERY_BROKER_URL="redis://127.0.0.1:26379/3"),
            lambda data: data["services"]["callback"]["volumes"][0].update(read_only=False),
        )
        for position, change in enumerate(changes):
            with self.subTest(case=position), self.assertRaises(ValueError):
                changed = copy.deepcopy(good)
                change(changed)
                smoke.validate_config(changed, PROJECT, smoke.IMAGES)

    def test_compose_always_uses_new_project_and_empty_env_file_without_persisting_secrets(self):
        def boundary(command, **_):
            stdout = json.dumps([{"Id": "sha256:" + "b" * 64}]) if command[:3] == ["docker", "image", "inspect"] else ""
            return subprocess.CompletedProcess(command, 0, stdout, "")

        with tempfile.TemporaryDirectory() as directory, patch.object(smoke, "ROOT", Path(directory)), \
                patch.object(smoke.subprocess, "run", side_effect=boundary) as docker:
            fixture = smoke.Fixture(smoke.IMAGES)
            fixture.compose("config", "--quiet")
            command = docker.call_args.args[0]
            self.assertEqual(command[:4], ["docker", "compose", "--project-name", fixture.project])
            self.assertNotEqual(fixture.project, "nexuscore")
            self.assertEqual((fixture.directory / "empty.env").read_text(), "")
            text = (fixture.directory / "compose.json").read_text()
            for name in ("SMOKE_DB_PASSWORD", "SMOKE_WEB_SECRET", "SMOKE_AUTH_SECRET", "SMOKE_SIGNING_SECRET"):
                self.assertNotIn(fixture.environment[name], text)
            self.assertNotIn("docker-compose.yml", command)
            self.assertIn(str(fixture.directory / "empty.env"), command)

    def test_cleanup_refuses_foreign_container_labels(self):
        calls = []

        def boundary(command, **_):
            calls.append(command)
            if command[:3] == ["docker", "image", "inspect"]:
                value = [{"Id": "sha256:" + "b" * 64}]
            elif command[-3:] == ["ps", "--all", "--quiet"]:
                return subprocess.CompletedProcess(command, 0, "foreign-id", "")
            elif command[:3] == ["docker", "network", "inspect"]:
                project = command[-1].removesuffix("_default")
                value = [{"Internal": True, "Labels": {"com.docker.compose.project": project}}]
            else:
                value = [{"Config": {"Labels": {"com.docker.compose.service": "auth_service", "com.docker.compose.project": "nexuscore"}}}]
            return subprocess.CompletedProcess(command, 0, json.dumps(value), "")

        with tempfile.TemporaryDirectory() as directory, patch.object(smoke, "ROOT", Path(directory)), \
                patch.object(smoke.subprocess, "run", side_effect=boundary):
            fixture = smoke.Fixture(smoke.IMAGES)
            with self.assertRaisesRegex(ValueError, "ownership"):
                fixture.stop()
        self.assertFalse(any("stop" in command for command in calls))

    def test_callback_verifies_signature_and_records_sensitive_header_names_only(self):
        secret = secrets.token_hex(32)
        server = ThreadingHTTPServer(("127.0.0.1", 0), smoke.receiver_handler(secret))
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        payload = b'{"synthetic":true}'
        try:
            self.assertEqual(smoke.request(base + "/receive", "POST", payload)[0], 401)
            signature = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
            self.assertEqual(smoke.request(base + "/receive", "POST", payload, {
                "X-Webhook-Signature": signature, "Authorization": "Bearer synthetic-unused"})[0], 200)
            receipt = smoke.request(base + "/receipt")[1]
            self.assertEqual(len(receipt["records"]), 1)
            self.assertEqual(receipt["records"][0]["body"], {"synthetic": True})
            self.assertEqual(receipt["records"][0]["sensitive_headers"], ["authorization"])
            self.assertNotIn("synthetic-unused", json.dumps(receipt))
            self.assertNotIn(signature, json.dumps(receipt))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_requests_ignore_proxy_and_refuse_redirects_and_non_loopback_urls(self):
        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/secret")
                self.end_headers()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "no_proxy": ""}), \
                    self.assertRaisesRegex(ValueError, "redirect"):
                smoke.request(f"http://127.0.0.1:{server.server_port}/health")
            for url in ("http://example.com/health", "http://192.168.0.1/health", "http://synthetic@127.0.0.1/health"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    smoke.request(url)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_optimized_cli_exits_before_fixture_creation(self):
        script = Path(smoke.__file__).resolve()
        for flags, environment in ((["-O"], {}), (["-OO"], {}), ([], {"PYTHONOPTIMIZE": "1"})):
            with self.subTest(flags=flags):
                result = subprocess.run([sys.executable, *flags, str(script), "--help"],
                    capture_output=True, text=True, timeout=10, env={**os.environ, **environment}, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("STOP: VerificationError; details withheld", result.stderr)
                self.assertNotIn("RECEIPT", result.stdout)


if __name__ == "__main__":
    unittest.main()
