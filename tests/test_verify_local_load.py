"""Loopback probe regressions using mocked HTTP and disposable local listeners."""

import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
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
            for duration, concurrency in ((4, 1), (61, 1), (5, 0), (5, 17), (5.5, 1), (5, 1.5), (5, True)):
                with self.subTest(duration=duration, concurrency=concurrency), self.assertRaises(ValueError):
                    verify("http://127.0.0.1/health", 200, duration, concurrency)
            client.assert_not_called()

    def test_invalid_probe_inputs_are_usage_errors_without_input_disclosure(self):
        cases = (
            ["http://synthetic-private-host.example/health"],
            ["http://127.0.0.1:0/health"], ["http://127.0.0.1:65536/health"],
            ["http://127.0.0.1:synthetic-private-port/health"], ["http://[invalid/health"],
            ["http://127.0.0.1/\thealth"], ["\x00http://127.0.0.1/health"],
            ["\x01http://127.0.0.1/health"], ["http://127.0.0.1/health\n"],
            [" http://127.0.0.1/health"], ["http://127.0.0.1/health\x7f"],
            ["http://synthetic-private-user@127.0.0.1/health"],
            ["http://127.0.0.1/health?synthetic-private-key=value"],
            ["http://127.0.0.1/health", "--duration", "4"],
            ["http://127.0.0.1/health", "--concurrency", "17"],
            ["http://127.0.0.1/health", "--duration", "synthetic-private-duration"],
            ["http://127.0.0.1/health", "--concurrency", "synthetic-private-concurrency"],
            ["http://127.0.0.1/health", "--expected", "synthetic-private-status"],
            ["http://127.0.0.1/health", "--expected", "418"],
            ["http://127.0.0.1/health", "--max-p95-ms", "synthetic-private-limit"],
            ["http://127.0.0.1/health", "--synthetic-private-option"],
            ["http://127.0.0.1/health", "synthetic-private-extra"],
            ["http://127.0.0.1/health", "--output"],
        )
        with patch("scripts.verify_local_load.httpx.Client") as client:
            for arguments in cases:
                with self.subTest(arguments=arguments):
                    with contextlib.redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit) as error:
                        main(arguments)
                    self.assertEqual(error.exception.code, 2)
                    self.assertNotIn("synthetic-private", errors.getvalue())
                    self.assertNotIn("Traceback", errors.getvalue())
                    self.assertIn("Invalid arguments; details withheld", errors.getvalue())
            client.assert_not_called()

    def test_direct_probe_rejects_unsupported_status_before_http(self):
        with patch("scripts.verify_local_load.httpx.Client") as client:
            for status in (0, 201, 302, True):
                with self.subTest(status=status), self.assertRaisesRegex(ValueError, "Expected status"):
                    verify("http://127.0.0.1/health", status, 5, 1)
            client.assert_not_called()

    def test_actual_cli_syntax_errors_withhold_arguments_and_keep_help(self):
        script = Path(__file__).resolve().parents[1] / "scripts/verify_local_load.py"
        for arguments in (("--duration", "synthetic-private-value"), ("--synthetic-private-option",)):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(script), "http://127.0.0.1:1/health", *arguments],
                    capture_output=True, text=True, timeout=10, check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("Invalid arguments; details withheld", result.stderr)
                self.assertNotIn("synthetic-private", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True,
                                text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--max-p95-ms", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_optimization_cannot_disable_url_guard(self):
        script = Path(__file__).resolve().parents[1] / "scripts/verify_local_load.py"
        for flags, environment in ((["-O"], {}), (["-OO"], {}), ([], {"PYTHONOPTIMIZE": "1"})):
            with self.subTest(flags=flags, environment=environment):
                result = subprocess.run(
                    [sys.executable, *flags, str(script), "http://127.0.0.1:1/health"],
                    env={**os.environ, **environment}, capture_output=True, text=True, timeout=10, check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid arguments; details withheld", result.stderr)
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

    def test_short_sample_p95_does_not_hide_a_slow_request_from_gate(self):
        with patch("scripts.verify_local_load.httpx.Client") as factory, \
                patch("scripts.verify_local_load.time.monotonic", side_effect=[0, 0, 0, 1, 6, 6]), \
                patch("scripts.verify_local_load.time.perf_counter", side_effect=[0, .001, 0, .1]), \
                contextlib.redirect_stdout(io.StringIO()) as output, \
                contextlib.redirect_stderr(io.StringIO()):
            factory.return_value.__enter__.return_value.get.return_value = httpx.Response(200)
            result = main(["http://127.0.0.1/health", "--duration", "5", "--concurrency", "1",
                           "--max-p95-ms", "50"])
        self.assertEqual(result, 1)
        report = json.loads(output.getvalue())
        self.assertEqual(report["requests"], 2)
        self.assertEqual(report["p95_ms"], 100)

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
                patch("scripts.verify_local_load.new_descriptor") as writer, \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main(["http://127.0.0.1/health"]), 0)
        probe.assert_called_once_with("http://127.0.0.1/health", 200, 30, 8)
        writer.assert_not_called()
        self.assertEqual(errors.getvalue(), "")

    def test_existing_output_or_missing_parent_fails_before_probe(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("scripts.verify_local_load.verify") as probe:
            existing = Path(directory) / "report.json"
            existing.write_text("preserved", encoding="utf-8")
            for destination in (existing, Path(directory), Path(directory) / "missing" / "report.json"):
                with self.subTest(destination=destination), \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    main(["http://127.0.0.1/health", "--output", str(destination)])
                self.assertEqual(error.exception.code, 2)
            probe.assert_not_called()
            self.assertEqual(existing.read_text(encoding="utf-8"), "preserved")

    def test_output_created_during_probe_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "report.json"

            def probe(*args):
                destination.write_text("concurrent report", encoding="utf-8")
                return {"p95_ms": 1}

            with patch("scripts.verify_local_load.verify", side_effect=probe), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["http://127.0.0.1/health", "--output", str(destination)])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(destination.read_text(encoding="utf-8"), "concurrent report")

    def test_probe_failure_does_not_create_report(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "report.json"
            with patch("scripts.verify_local_load.verify", side_effect=ValueError("Probe failed")), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["http://127.0.0.1/health", "--output", str(destination)])
            self.assertEqual(error.exception.code, 2)
            self.assertFalse(destination.exists())

    def test_output_link_is_rejected_before_probe_even_when_dangling(self):
        with tempfile.TemporaryDirectory() as directory:
            destination, target = (Path(directory) / name for name in ("report.json", "target.json"))
            try:
                destination.symlink_to(target)
            except OSError:
                self.skipTest("Symlink creation is unavailable")
            with patch("scripts.verify_local_load.verify", return_value={"p95_ms": 1}) as probe, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["http://127.0.0.1/health", "--output", str(destination)])
            self.assertEqual(error.exception.code, 2)
            probe.assert_not_called()
            self.assertTrue(destination.is_symlink())
            self.assertFalse(target.exists())

    def test_output_link_created_during_probe_never_redirects_report(self):
        for occupied in (False, True):
            with self.subTest(occupied=occupied), tempfile.TemporaryDirectory() as directory:
                destination, target = (Path(directory) / name for name in ("report.json", "target.json"))
                if occupied:
                    target.write_bytes(b"preserved")
                try:
                    destination.symlink_to(target)
                    destination.unlink()
                except OSError:
                    self.skipTest("Symlink creation is unavailable")

                def probe(*args, destination=destination, target=target):
                    destination.symlink_to(target)
                    return {"p95_ms": 1}

                with patch("scripts.verify_local_load.verify", side_effect=probe) as request, \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    main(["http://127.0.0.1/health", "--output", str(destination)])
                self.assertEqual(error.exception.code, 2)
                request.assert_called_once()
                self.assertTrue(destination.is_symlink())
                self.assertEqual(target.read_bytes() if occupied else target.exists(), b"preserved" if occupied else False)

    def test_transport_and_status_failures_are_safe_cli_failures_without_reports(self):
        failures = (httpx.ConnectError("synthetic-private-connection"),
                    httpx.ReadTimeout("synthetic-private-timeout"),
                    httpx.RemoteProtocolError("synthetic-private-protocol"), None)
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory, \
                    patch("scripts.verify_local_load.httpx.Client") as factory, \
                    patch("scripts.verify_local_load.time.monotonic", side_effect=[0, 0, 0]), \
                    contextlib.redirect_stdout(io.StringIO()) as output, \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                client = factory.return_value.__enter__.return_value
                client.get.side_effect = failure
                client.get.return_value = httpx.Response(503, text="synthetic-private-body")
                destination = Path(directory) / "report.json"
                self.assertEqual(main(["http://127.0.0.1/health", "--concurrency", "1",
                                       "--output", str(destination)]), 1)
                self.assertFalse(destination.exists())
                self.assertEqual(output.getvalue(), "")
                self.assertIn("Local HTTP probe failed", errors.getvalue())
                self.assertNotIn("synthetic-private", errors.getvalue())
                self.assertNotIn("Traceback", errors.getvalue())

    def test_cli_connection_refusal_has_no_traceback_or_report(self):
        script = Path(__file__).resolve().parents[1] / "scripts/verify_local_load.py"
        with socket.socket() as bound, tempfile.TemporaryDirectory() as directory:
            bound.bind(("127.0.0.1", 0))
            url = f"http://127.0.0.1:{bound.getsockname()[1]}/health"
            destination = Path(directory) / "report.json"
            result = subprocess.run(
                [sys.executable, str(script), url, "--concurrency", "1", "--output", str(destination)],
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertIn("Local HTTP probe failed (ConnectError)", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertNotIn(url, result.stderr)
            self.assertFalse(destination.exists())

    def test_output_open_or_write_failure_is_reported_as_error(self):
        for operation in ("open", "write"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory, \
                    patch("scripts.verify_local_load.verify", return_value={"p95_ms": 1}), \
                    patch("scripts.verify_local_load.new_descriptor", return_value=-1) as descriptor, \
                    patch("scripts.verify_local_load.os.fdopen") as writer, \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                if operation == "open":
                    descriptor.side_effect = PermissionError
                else:
                    writer.return_value.__enter__.return_value.write.side_effect = OSError
                with self.assertRaises(SystemExit) as error:
                    main(["http://127.0.0.1/health", "--output", str(Path(directory) / "report.json")])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("Invalid arguments; details withheld", errors.getvalue())

    def test_cli_gate_and_export_against_isolated_http_server(self):
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
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server, \
                tempfile.TemporaryDirectory() as directory:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/health"
                for limit, exit_code in (("5000", 0), ("0.001", 1)):
                    with self.subTest(limit=limit):
                        destination = Path(directory) / f"report-{exit_code}.json"
                        result = subprocess.run(
                            [sys.executable, str(script), url, "--duration", "5", "--concurrency", "1",
                             "--max-p95-ms", limit, "--output", str(destination)],
                            capture_output=True, text=True, timeout=20, check=False,
                        )
                        self.assertEqual(result.returncode, exit_code, result.stderr)
                        report = json.loads(result.stdout)
                        self.assertEqual(destination.read_text(encoding="utf-8"), result.stdout)
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
