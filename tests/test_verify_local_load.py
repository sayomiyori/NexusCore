"""Regression checks for the loopback-only GET probe; no real network traffic."""

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from scripts.verify_local_load import verify


class LocalLoadTests(unittest.TestCase):
    def test_unsafe_urls_are_rejected_before_http(self):
        urls = (
            "https://127.0.0.1/health", "http://192.168.0.1/health",
            "http://example.com/health", "http://127.0.0.1/health?key=synthetic",
            "http://127.0.0.1/health#fragment", "http://synthetic@127.0.0.1/health",
            "http://127.0.0.1/api/v1/tenants", "file:///health",
        )
        with patch("scripts.verify_local_load.httpx.Client") as client:
            for url in urls:
                with self.subTest(url=url), self.assertRaises((AssertionError, ValueError)):
                    verify(url, 200, 5, 1)
            client.assert_not_called()

    def test_invalid_bounds_are_rejected_before_http(self):
        with patch("scripts.verify_local_load.httpx.Client") as client:
            for duration, concurrency in ((4, 1), (61, 1), (5, 0), (5, 17)):
                with self.subTest(duration=duration, concurrency=concurrency), self.assertRaises(AssertionError):
                    verify("http://127.0.0.1/health", 200, duration, concurrency)
            client.assert_not_called()

    def test_optimization_cannot_disable_url_guard(self):
        script = Path(__file__).resolve().parents[1] / "scripts/verify_local_load.py"
        for flags, environment in ((["-O"], {}), (["-OO"], {}), ([], {"PYTHONOPTIMIZE": "1"})):
            with self.subTest(flags=flags, environment=environment):
                result = subprocess.run(
                    [sys.executable, *flags, str(script), "http://127.0.0.1:1/health"],
                    env={**os.environ, **environment}, capture_output=True, text=True, timeout=10, check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Optimized Python disables safety assertions", result.stderr)
                self.assertNotIn("ConnectError", result.stderr)

    def test_loopback_get_and_report_without_proxy_redirect_or_body(self):
        for url, status in (("http://127.0.0.1/health", 200), ("http://[::1]/health/ready", 200),
                            ("http://localhost/api/v1/auth/me", 401)):
            with self.subTest(url=url):
                client = Mock()
                client.get.return_value = httpx.Response(status, text="synthetic-private-body")
                with patch("scripts.verify_local_load.httpx.Client") as factory, \
                        patch("scripts.verify_local_load.time.monotonic", side_effect=[0, 0, 0, 6, 6]), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    factory.return_value.__enter__.return_value = client
                    report = verify(url, status, 5, 1)
                factory.assert_called_once_with(timeout=5, trust_env=False, follow_redirects=False)
                client.get.assert_called_once_with(url)
                self.assertEqual(report["requests"], 1)
                self.assertEqual(report["expected_status"], status)
                self.assertEqual(json.loads(output.getvalue()), report)
                self.assertNotIn(url, output.getvalue())
                self.assertNotIn("synthetic-private-body", output.getvalue())

    def test_unexpected_redirect_is_rejected(self):
        with patch("scripts.verify_local_load.httpx.Client") as factory, \
                patch("scripts.verify_local_load.time.monotonic", side_effect=[0, 0, 0]):
            factory.return_value.__enter__.return_value.get.return_value = httpx.Response(
                302, headers={"location": "https://example.com/health"},
            )
            with self.assertRaisesRegex(AssertionError, "Unexpected local HTTP status"):
                verify("http://127.0.0.1/health", 200, 5, 1)
            factory.assert_called_once_with(timeout=5, trust_env=False, follow_redirects=False)


if __name__ == "__main__":
    unittest.main()
