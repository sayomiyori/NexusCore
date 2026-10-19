"""Teardown keeps owned dependencies alive and cannot certify a forced exit."""

import copy
import unittest
from unittest.mock import Mock, call

from scripts import verify_stack as smoke


class FixtureShutdownTests(unittest.TestCase):
    def fixture(self):
        fixture = object.__new__(smoke.Fixture)
        fixture.scanners = {"legacy_scanner": None}
        items = {name: {"Id": name, "State": {"Running": True, "OOMKilled": False, "ExitCode": 0},
                        "HostConfig": {"RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}}}
                 for name in ("postgres", "redis", "callback", "agent_worker", "legacy_scanner")}
        stopped = copy.deepcopy(items)
        for name, item in stopped.items():
            item["State"].update(Running=False, ExitCode=143 if name in fixture.scanners else 0)
        fixture.owned = Mock(side_effect=[items, stopped])
        fixture.run = Mock()
        fixture.compose = Mock()
        return fixture, items, stopped

    def test_applications_stop_before_infrastructure_after_restart_disable(self):
        fixture, _, _ = self.fixture()
        order = Mock()
        order.attach_mock(fixture.run, "docker")
        order.attach_mock(fixture.compose, "compose")
        fixture.stop()
        self.assertEqual(order.mock_calls, [call.docker(["docker", "update", "--restart=no", "legacy_scanner"]),
                                           call.compose("stop", "--timeout", "30", "agent_worker", "legacy_scanner"),
                                           call.compose("stop", "--timeout", "10")])

    def test_infrastructure_stop_still_runs_when_application_stop_fails(self):
        fixture, _, _ = self.fixture()
        fixture.compose.side_effect = [RuntimeError("synthetic stop failure"), ""]
        with self.assertRaises(RuntimeError):
            fixture.stop()
        self.assertEqual(fixture.compose.call_args.args, ("stop", "--timeout", "10"))

    def test_forced_exit_and_oom_fail_even_when_containers_are_stopped(self):
        for exit_code, oom in ((137, False), (1, False), (0, True)):
            with self.subTest(exit_code=exit_code, oom=oom):
                fixture, _, stopped = self.fixture()
                stopped["agent_worker"]["State"].update(ExitCode=exit_code, OOMKilled=oom)
                with self.assertRaises(smoke.VerificationError):
                    fixture.stop()


if __name__ == "__main__":
    unittest.main()
