"""Portable encryption regressions using generated keys and disposable files only."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from scripts import backup_artifact as backup

SCRIPT = Path(backup.__file__).resolve()


class BackupArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.key = self.root / "synthetic.backup-key"
        self.key.write_bytes(Fernet.generate_key())
        self.source = self.root / "synthetic.dump"
        self.source.write_bytes(b"PGDMP\x00synthetic private content\xff")
        self.output = self.root / "artifact.fernet"

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, timeout=10, check=False)

    def test_separate_process_key_generation_encryption_and_decryption(self):
        key = self.root / "generated.backup-key"
        self.assertEqual(self.cli("keygen", "--output", key).returncode, 0)
        self.assertEqual(len(key.read_bytes()), 44)
        for data in (self.source.read_bytes(), b""):
            with self.subTest(empty=not data):
                source = self.root / ("empty" if not data else "binary")
                source.write_bytes(data)
                encrypted = source.with_suffix(".fernet")
                restored = source.with_suffix(".restored")
                result = self.cli("encrypt", source, "--key-file", key, "--output", encrypted)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn(data or b"synthetic private content", encrypted.read_bytes())
                self.assertEqual(self.cli("decrypt", encrypted, "--key-file", key, "--output", restored).returncode, 0)
                self.assertEqual(restored.read_bytes(), data)
                if os.name != "nt":
                    self.assertEqual(restored.stat().st_mode & 0o777, 0o600)

    def test_wrong_key_corruption_and_truncation_create_no_plaintext_or_disclosure(self):
        token = Fernet(self.key.read_bytes()).encrypt(self.source.read_bytes())
        wrong = self.root / "wrong.backup-key"
        wrong.write_bytes(Fernet.generate_key())
        damaged = bytearray(token)
        damaged[len(damaged) // 2] = ord("A") if damaged[len(damaged) // 2] != ord("A") else ord("B")
        for index, (payload, key) in enumerate(((token, wrong), (bytes(damaged), self.key), (token[:-10], self.key), (b"invalid", self.key))):
            with self.subTest(index=index):
                encrypted = self.root / f"damaged-{index}.fernet"
                encrypted.write_bytes(payload)
                restored = self.root / f"recovered-{index}"
                result = self.cli("decrypt", encrypted, "--key-file", key, "--output", restored)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(restored.exists())
                self.assertEqual(result.stdout, b"")
                for private in (str(self.root).encode(), self.key.read_bytes(), b"synthetic private content", b"Traceback"):
                    self.assertNotIn(private, result.stderr)

    def test_existing_outputs_and_same_source_are_preserved(self):
        for destination in (self.source, self.key, self.root, self.root / "occupied"):
            if destination.name == "occupied":
                destination.write_bytes(b"preserve me")
            original = destination.read_bytes() if destination.is_file() else None
            result = self.cli("encrypt", self.source, "--key-file", self.key, "--output", destination)
            self.assertEqual(result.returncode, 1)
            if original is not None:
                self.assertEqual(destination.read_bytes(), original)
        original = self.key.read_bytes()
        self.assertEqual(self.cli("keygen", "--output", self.key).returncode, 1)
        self.assertEqual(self.key.read_bytes(), original)

    def test_racing_output_creation_is_not_overwritten(self):
        actual = backup.write_new

        def raced(path, data):
            path.write_bytes(b"racing writer")
            return actual(path, data)

        with patch.object(backup, "write_new", side_effect=raced), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(backup.main(["encrypt", str(self.source), "--key-file", str(self.key), "--output", str(self.output)]), 1)
        self.assertEqual(self.output.read_bytes(), b"racing writer")

    def test_invalid_keys_missing_files_and_nonregular_inputs_fail_before_output(self):
        for key_data in (b"", b"short", b"!" * 44, b"a" * 45):
            self.key.write_bytes(key_data)
            self.assertEqual(self.cli("encrypt", self.source, "--key-file", self.key, "--output", self.output).returncode, 1)
            self.assertFalse(self.output.exists())
        self.key.write_bytes(Fernet.generate_key())
        for source in (self.root, self.root / "missing"):
            self.assertEqual(self.cli("encrypt", source, "--key-file", self.key, "--output", self.output).returncode, 1)
            self.assertFalse(self.output.exists())
        if os.name != "nt":
            fifo = self.root / "fifo"
            os.mkfifo(fifo)
            self.assertEqual(self.cli("encrypt", fifo, "--key-file", self.key, "--output", self.output).returncode, 1)

    def test_size_limits_apply_to_key_plaintext_ciphertext_and_authenticated_result(self):
        with patch.object(backup, "MAX_PLAINTEXT", 4), patch.object(backup, "MAX_CIPHERTEXT", 128):
            with self.assertRaises(ValueError):
                backup.transform(self.source, self.output, self.key, decrypt=False)
            token = Fernet(self.key.read_bytes()).encrypt(b"12345")
            self.source.write_bytes(token)
            with self.assertRaises(ValueError):
                backup.transform(self.source, self.output, self.key, decrypt=True)
            self.source.write_bytes(b"x" * 129)
            with self.assertRaises(ValueError):
                backup.transform(self.source, self.output, self.key, decrypt=True)
        self.assertFalse(self.output.exists())

    def test_symlink_inputs_and_outputs_do_not_follow_or_overwrite_targets(self):
        link = self.root / "link"
        try:
            link.symlink_to(self.source)
        except OSError:
            self.skipTest("Symlink creation is unavailable")
        original = self.source.read_bytes()
        result = self.cli("encrypt", link, "--key-file", self.key, "--output", self.output)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.output.exists())
        result = self.cli("encrypt", self.source, "--key-file", self.key, "--output", link)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.source.read_bytes(), original)

    def test_io_failures_do_not_report_success_or_expose_paths(self):
        missing_parent = self.root / "synthetic-private-dir" / "out"
        result = self.cli("encrypt", self.source, "--key-file", self.key, "--output", missing_parent)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(b"synthetic-private", result.stderr)
        self.assertFalse(missing_parent.exists())

    def test_dangling_symlink_output_and_creation_race_never_create_target(self):
        target = self.root / "redirected-plaintext"
        link = self.root / "dangling"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symlink creation is unavailable")
        result = self.cli("keygen", "--output", link)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(target.exists())
        token = self.root / "valid.fernet"
        token.write_bytes(Fernet(self.key.read_bytes()).encrypt(self.source.read_bytes()))
        result = self.cli("decrypt", token, "--key-file", self.key, "--output", link)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(target.exists())
        actual = backup.new_descriptor

        def raced(path):
            path.symlink_to(target)
            return actual(path)

        raced_output = self.root / "raced-link"
        with patch.object(backup, "new_descriptor", side_effect=raced), self.assertRaises(OSError):
            backup.write_new(raced_output, b"must never be redirected")
        self.assertTrue(raced_output.is_symlink())
        self.assertFalse(target.exists())

    def test_invalid_cli_syntax_does_not_echo_arguments(self):
        for args in (("synthetic-private-command",),
                     ("encrypt", "synthetic-private-source", "--key-file", "key", "--output", "output", "synthetic-private-extra")):
            result = self.cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn(b"synthetic-private", result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
