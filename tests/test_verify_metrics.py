"""Metrics endpoint acceptance, with only the HTTP connection boundary replaced."""

import contextlib
import copy
import http.client
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_verify_stack import PROJECT, resolved_config

from scripts import verify_metrics as metrics
from scripts import verify_stack as smoke
from scripts import verify_telegram_ai as ai


class MetricsSmokeTests(unittest.TestCase):
    def test_metrics_mount_rejects_foreign_source_writable_or_non_api_role(self):
        for failure in ("source", "writable", "role"):
            with self.subTest(failure=failure), self.assertRaises(ValueError):
                config = resolved_config()
                mount = next(item for item in config["services"]["auth_service"]["volumes"]
                             if item["target"] == "/verification/verify_metrics.py")
                if failure == "source":
                    mount["source"] = str(Path(smoke.__file__).with_name("backup_artifact.py"))
                elif failure == "writable":
                    mount["read_only"] = False
                else:
                    config["services"]["callback"]["volumes"].append(mount)
                smoke.validate_config(config, PROJECT, smoke.IMAGES)

    def test_host_stage_uses_only_original_owned_apis_and_exact_profile_commands(self):
        for platform in (False, True):
            with self.subTest(platform=platform), contextlib.redirect_stdout(io.StringIO()):
                fixture = Mock(controlled_ai=platform)
                fixture.items = {name: {"Id": name, "State": {"Running": True, "OOMKilled": False}} for name in smoke.LOAD_PATHS}
                fixture.owned.return_value = copy.deepcopy(fixture.items)

                def probe(*args, platform=platform):
                    role = args[-2] if platform else args[-1]
                    status = metrics.DENIALS[role][0] if platform and role in metrics.DENIALS else 200
                    return json.dumps({"status": status, "exported": status == 200})

                fixture.compose.side_effect = probe
                report = {}
                smoke.verify_metrics(fixture, report)
                self.assertEqual(set(report["checks"]), set(smoke.LOAD_PATHS))
                for command, role in zip(fixture.compose.call_args_list, smoke.LOAD_PATHS, strict=True):
                    self.assertEqual(command.args, ("exec", "-T", role, "python", "-B", "/verification/verify_metrics.py", role,
                                                    *(("--platform",) if platform else ())))
                fixture.owned.return_value["agent_service"]["Id"] = "replacement"
                fixture.compose.reset_mock()
                with self.assertRaises(ValueError):
                    smoke.verify_metrics(fixture, {})
                fixture.compose.assert_not_called()

    def test_both_drivers_retain_partial_metrics_and_stop_on_transport_failure(self):
        for platform in (False, True):
            driver = ai if platform else smoke
            entry = driver.main
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as directory, \
                    patch.object(smoke, "Fixture") as boundary, patch.object(driver, "verify", return_value={}), \
                    patch.object(smoke, "main") as legacy, contextlib.redirect_stdout(io.StringIO()):
                fixture = boundary.return_value
                fixture.project, fixture.directory, fixture.images = PROJECT, Path(directory), smoke.IMAGES
                fixture.controlled_ai, fixture.environment = platform, {}
                fixture.callback_origin = "http://192.168.0.4:8000"
                fixture.items = {name: {"Id": name, "State": {"Running": True, "OOMKilled": False}} for name in smoke.LOAD_PATHS}
                fixture.owned.return_value = fixture.items
                fixture.compose.side_effect = [json.dumps({"status": 200, "exported": True}),
                                               json.dumps({"status": 503 if platform else 200, "exported": not platform}),
                                               RuntimeError("synthetic-private-transport")]
                with self.assertRaises(RuntimeError):
                    entry([])
                receipt = json.loads((fixture.directory / "receipt.json").read_text())
                self.assertEqual(set(receipt["metrics"]["checks"]), {"auth_service", "webhook_service"})
                self.assertFalse(receipt["passed"])
                self.assertTrue(receipt["owned_containers_stopped"])
                fixture.stop.assert_called_once_with()
                legacy.assert_not_called()
                self.assertNotIn("synthetic-private", json.dumps(receipt))

    def test_standalone_markers_are_checked_without_saving_values_or_labels(self):
        for role, families in metrics.FAMILIES.items():
            with self.subTest(role=role), patch.object(metrics.http.client, "HTTPConnection") as factory:
                connection = factory.return_value
                response = connection.getresponse.return_value
                response.status = 200
                response.getheader.return_value = "text/plain; version=0.0.4; charset=utf-8"
                response.read.return_value = ("\n".join(f"# TYPE {name} {kind}" for name, kind in families.items()) +
                                              '\nexample{private="synthetic-private-label"} 123\n').encode()
                result = metrics.verify(role)
                factory.assert_called_once_with("127.0.0.1", 8000, timeout=5)
                connection.request.assert_called_once_with("GET", "/metrics")
                response.read.assert_called_once_with(metrics.MAX_BYTES + 1)
                connection.close.assert_called_once_with()
                self.assertEqual(result["checked_families"], sorted(families))
                self.assertTrue(result["exported"])
                self.assertNotIn("synthetic-private", json.dumps(result))

    def test_platform_denials_require_exact_status_and_non_exporting_json(self):
        for role, (status, detail) in metrics.DENIALS.items():
            with self.subTest(role=role), patch.object(metrics.http.client, "HTTPConnection") as factory:
                response = factory.return_value.getresponse.return_value
                response.status = status
                response.getheader.return_value = "application/json"
                response.read.return_value = json.dumps({"detail": detail}).encode()
                self.assertEqual(metrics.verify(role, True), {"status": status, "exported": False,
                                                             "checked_families": [], "bytes": len(response.read.return_value)})
                factory.return_value.close.assert_called_once_with()

    def test_platform_auth_retains_its_existing_exporter(self):
        with patch.object(metrics.http.client, "HTTPConnection") as factory:
            response = factory.return_value.getresponse.return_value
            response.status, response.getheader.return_value = 200, "text/plain"
            response.read.return_value = b"# TYPE auth_register_total counter\n# TYPE active_sessions_total gauge\n"
            self.assertTrue(metrics.verify("auth_service", True)["exported"])

    def test_wrong_status_type_missing_markers_and_oversize_fail_and_close(self):
        for status, content_type, body in ((302, "text/plain", b""), (200, "application/json", b"{}"),
                                           (200, "text/plain", b"# TYPE wrong counter\n"),
                                           (200, "text/plain", b"x" * (metrics.MAX_BYTES + 1)),
                                           (200, "text/plain", b"\xff")):
            with self.subTest(status=status, content_type=content_type, size=len(body)), \
                    patch.object(metrics.http.client, "HTTPConnection") as factory:
                response = factory.return_value.getresponse.return_value
                response.status, response.getheader.return_value, response.read.return_value = status, content_type, body
                with self.assertRaises(ValueError):
                    metrics.verify("auth_service")
                factory.return_value.close.assert_called_once_with()

    def test_widened_or_invalid_platform_denial_is_rejected(self):
        for body in (b'not json', b'{"detail":"Not found","private":"synthetic-private-value"}',
                     b'{"detail":"different"}', b'[]', b'null',
                     b'{"detail":"synthetic-private-value","detail":"Not found"}'):
            with self.subTest(body=body), patch.object(metrics.http.client, "HTTPConnection") as factory:
                response = factory.return_value.getresponse.return_value
                response.status, response.getheader.return_value, response.read.return_value = 404, "application/json", body
                with self.assertRaises(ValueError):
                    metrics.verify("agent_service", True)
                factory.return_value.close.assert_called_once_with()

    def test_cli_failure_withholds_details_and_never_prints_success_json(self):
        for failure in (OSError("synthetic-private-address"), http.client.HTTPException("synthetic-private-protocol")):
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(metrics.http.client, "HTTPConnection") as factory, \
                    contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
                factory.return_value.request.side_effect = failure
                self.assertEqual(metrics.main(["agent_service", "--platform"]), 1)
                factory.return_value.close.assert_called_once_with()
                self.assertEqual(output.getvalue(), "")
                self.assertNotIn("synthetic-private", errors.getvalue())

    def test_cli_success_prints_only_the_safe_metadata_summary(self):
        with patch.object(metrics.http.client, "HTTPConnection") as factory, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            response = factory.return_value.getresponse.return_value
            response.status, response.getheader.return_value = 200, "text/plain"
            response.read.return_value = (b"# TYPE auth_register_total counter\n# TYPE active_sessions_total gauge\n"
                                          b'example{private="synthetic-private-label"} 123\n')
            self.assertEqual(metrics.main(["auth_service", "--platform"]), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], 200)
            self.assertNotIn("synthetic-private", output.getvalue())

    def test_invalid_role_or_profile_fails_before_http(self):
        with patch.object(metrics.http.client, "HTTPConnection") as connection:
            for role, platform in (("foreign", False), ("auth_service", "false")):
                with self.assertRaises(ValueError):
                    metrics.verify(role, platform)
            connection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
