"""Exercise edge fixture startup at the Docker subprocess boundary."""

import ipaddress
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import verify_telegram_edge as edge


class EdgeFixtureStartupTests(unittest.TestCase):
    def run_startup(self, failures, cleanup_failure=False):
        starts = []
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            operation = command[command.index("-f") + 4]
            if operation == "up":
                override = json.loads(Path(command[command.index("-f") + 3]).read_text())
                starts.append(override)
                if len(starts) <= len(failures):
                    return subprocess.CompletedProcess(command, 1, "", failures[len(starts) - 1])
            if operation == "down" and cleanup_failure:
                return subprocess.CompletedProcess(command, 1, "", "cleanup failed")
            if operation == "port":
                raise RuntimeError("probe boundary")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(edge.subprocess, "run", side_effect=run), \
                patch.object(edge.secrets, "randbits", side_effect=range(20)), \
                patch("sys.argv", ["edge", "--python-image", "synthetic-image"]), \
                self.assertRaises(RuntimeError) as error:
            edge.main()
        return str(error.exception), starts, commands

    def test_subnets_are_distinct_private_ipv4_ranges(self):
        for salt in (0, 1, 0xFFFFFFFF):
            with self.subTest(salt=salt), patch.object(edge.secrets, "randbits", return_value=salt):
                subnets = edge.pick_subnets()
                self.assertNotEqual(*subnets)
                for subnet in subnets:
                    network = ipaddress.ip_network(subnet)
                    self.assertTrue(network.is_private)
                    self.assertEqual(network.prefixlen, 24)

    def test_only_subnet_collision_is_retried_with_owned_cleanup(self):
        error, starts, commands = self.run_startup([
            "Error response from daemon: invalid pool request: Pool overlaps with other one on this address space",
        ])
        self.assertEqual(error, "probe boundary")
        self.assertEqual(len(starts), 2)
        self.assertNotEqual(starts[0]["networks"], starts[1]["networks"])
        projects = {command[command.index("--project-name") + 1] for command in commands}
        self.assertEqual(len(projects), 1)
        self.assertTrue(next(iter(projects)).startswith("nexus-edge-check-"))
        for command in commands:
            self.assertNotIn("--volumes", command)

    def test_unrelated_startup_error_is_not_retried(self):
        error, starts, _ = self.run_startup(["synthetic image is unavailable"] * 8)
        self.assertEqual(len(starts), 1)
        self.assertIn("synthetic image is unavailable", error)

    def test_collision_retries_are_bounded(self):
        error, starts, _ = self.run_startup(["Pool overlaps with other one on this address space"] * 8)
        self.assertEqual(len(starts), 8)
        self.assertIn("Pool overlaps", error)

    def test_failed_cleanup_prevents_another_start(self):
        error, starts, _ = self.run_startup(
            ["Pool overlaps with other one on this address space"] * 8, cleanup_failure=True,
        )
        self.assertEqual(len(starts), 1)
        self.assertIn("cleanup failed", error)


if __name__ == "__main__":
    unittest.main()
