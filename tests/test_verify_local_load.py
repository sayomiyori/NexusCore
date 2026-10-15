"""Loopback probe regressions using mocked HTTP and disposable local listeners."""

import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from scripts.verify_local_load import main, verify


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

    def test_latency_gate_accepts_below_and_equal_limit_and_rejects_above(self):
        for p95, expected_exit in ((12.33, 0), (12.34, 0), (12.35, 1)):
            with self.subTest(p95=p95), \
                    patch("scripts.verify_local_load.verify", return_value={"p95_ms": p95}) as probe, \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                result = main(["http://127.0.0.1/health", "--max-p95-ms", "12.34"])
            self.assertEqual(result, expected_exit)
            self.assertEqual(bool(errors.getvalue()), bool(expected_exit))
            probe.assert_called_once_with("http://127.0.0.1/health", 200, 30, 8)

    def test_invalid_latency_limits_fail_before_probe(self):
        with patch("scripts.verify_local_load.verify") as probe:
            for limit in ("0", "-1", "nan", "inf", "-inf", "invalid"):
                with self.subTest(limit=limit), \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    main(["http://127.0.0.1/health", f"--max-p95-ms={limit}"])
                self.assertEqual(error.exception.code, 2)
            probe.assert_not_called()

    def test_cli_without_latency_limit_preserves_defaults(self):
        with patch("scripts.verify_local_load.verify", return_value={"p95_ms": 99999}) as probe, \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main(["http://127.0.0.1/health"]), 0)
        probe.assert_called_once_with("http://127.0.0.1/health", 200, 30, 8)
        self.assertEqual(errors.getvalue(), "")

    def test_cli_latency_gate_against_isolated_http_server(self):
        paths = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                paths.append(self.path)
                time.sleep(.01)
                body = b"synthetic-private-body"
                self.send_response(200 if self.path == "/health" else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        script = Path(__file__).resolve().parents[1] / "scripts/verify_local_load.py"
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/health"
                for limit, exit_code in (("5000", 0), ("0.001", 1)):
                    with self.subTest(limit=limit):
                        result = subprocess.run(
                            [sys.executable, str(script), url, "--duration", "5", "--concurrency", "1",
                             "--max-p95-ms", limit],
                            capture_output=True, text=True, timeout=20, check=False,
                        )
                        self.assertEqual(result.returncode, exit_code, result.stderr)
                        report = json.loads(result.stdout)
                        self.assertGreater(report["requests"], 0)
                        self.assertEqual(report["p95_ms"] > float(limit), bool(exit_code))
                        self.assertNotIn(url, result.stdout)
                        self.assertNotIn("synthetic-private-body", result.stdout)
            finally:
                server.shutdown()
                thread.join(timeout=5)
        self.assertTrue(paths)
        self.assertEqual(set(paths), {"/health"})


if __name__ == "__main__":
    unittest.main()
