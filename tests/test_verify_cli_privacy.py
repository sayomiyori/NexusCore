"""CLI syntax diagnostics must not echo private arguments or start a runtime."""

import contextlib
import io
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts import verify_metrics as metrics
from scripts import verify_stack as smoke
from scripts import verify_telegram_ai as ai
from scripts import verify_telegram_edge as edge

CASES = (
    (metrics, (['synthetic-private-role'], ['auth_service', '--synthetic-private-option'],
               ['auth_service', 'synthetic-private-extra'])),
    (smoke, (['--synthetic-private-option'], ['synthetic-private-extra'], ['--auth-image'])),
    (ai, (['--synthetic-private-option'], ['synthetic-private-extra'], ['--agent-image'])),
    (edge, (['--python-image', 'synthetic-image', '--synthetic-private-option'],
            ['--python-image', 'synthetic-image', 'synthetic-private-extra'], ['--python-image'])),
)


class VerificationCliPrivacyTests(unittest.TestCase):
    def test_invalid_arguments_are_static_errors_before_runtime_boundaries(self):
        for module, cases in CASES:
            for arguments in cases:
                with self.subTest(cli=module.__name__, arguments=arguments), \
                        patch.object(sys, 'argv', [module.__file__, *arguments]), \
                        patch.object(smoke, 'Fixture') as fixture, \
                        patch.object(metrics.http.client, 'HTTPConnection') as connection, \
                        patch.object(edge.tempfile, 'TemporaryDirectory') as directory, \
                        patch.object(subprocess, 'run') as runtime, \
                        contextlib.redirect_stdout(io.StringIO()) as output, \
                        contextlib.redirect_stderr(io.StringIO()) as errors, self.assertRaises(SystemExit) as error:
                    module.main() if module is edge else module.main(arguments)
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(output.getvalue(), '')
                self.assertIn('Invalid arguments; details withheld', errors.getvalue())
                self.assertNotIn('synthetic-private', errors.getvalue())
                self.assertNotIn('Traceback', errors.getvalue())
                for boundary in (fixture, connection, directory, runtime):
                    boundary.assert_not_called()

    def test_actual_cli_rejected_arguments_are_not_echoed(self):
        for module, cases in CASES:
            for arguments in cases[:2]:
                with self.subTest(cli=module.__name__, arguments=arguments):
                    result = subprocess.run([sys.executable, '-B', module.__file__, *arguments],
                                            capture_output=True, text=True, timeout=10, check=False)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, '')
                    self.assertIn('Invalid arguments; details withheld', result.stderr)
                    self.assertNotIn('synthetic-private', result.stderr)
                    self.assertNotIn('Traceback', result.stderr)

    def test_actual_help_remains_available_without_runtime(self):
        for module, _ in CASES:
            with self.subTest(cli=module.__name__):
                result = subprocess.run([sys.executable, '-B', module.__file__, '--help'],
                                        capture_output=True, text=True, timeout=10, check=False)
                self.assertEqual(result.returncode, 0)
                self.assertIn('usage:', result.stdout)
                self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
