import importlib.util
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / 'coordination_hub' / 'test_access.py'

@unittest.skipUnless(os.name == 'nt', 'Windows ACL test')
class AccessTests(unittest.TestCase):
    def test_private_test_directory_is_protected_and_writable(self):
        self.assertTrue(MODULE.exists(), 'Test ACL implementation must exist')
        spec = importlib.util.spec_from_file_location('coordination_test_access', MODULE)
        access = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(access)
        from coordination_hub.directory_guard import test_directory_guard
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'private'
            directory.mkdir()
            with test_directory_guard(directory):
                access.restrict_test_directory(directory)
                (directory / 'synthetic.txt').write_text('synthetic', encoding='utf-8')
                self.assertEqual((directory / 'synthetic.txt').read_text(encoding='utf-8'), 'synthetic')

    def test_refuses_existing_data(self):
        self.assertTrue(MODULE.exists(), 'Test ACL implementation must exist')
        spec = importlib.util.spec_from_file_location('coordination_test_access2', MODULE)
        access = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(access)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'private'
            directory.mkdir()
            (directory / 'existing.txt').write_text('synthetic', encoding='utf-8')
            with self.assertRaises(ValueError):
                access.restrict_test_directory(directory)

    def test_database_sidecars_and_backup_inherit_acl(self):
        spec = importlib.util.spec_from_file_location('coordination_test_access3', MODULE)
        access = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(access)
        from coordination_hub.backup import backup_database
        from coordination_hub.store import Store

        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'private'
            directory.mkdir()
            access.restrict_test_directory(directory)
            source, backup = directory / 'hub.sqlite3', directory / 'backup.sqlite3'
            Store(source)
            writer = sqlite3.connect(source)
            try:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('PRAGMA wal_autocheckpoint=0')
                writer.execute("INSERT INTO messages VALUES ('acl-test','security','codex','Synthetic',1)")
                writer.commit()
                self.assertTrue(Path(str(source) + '-wal').exists())
                self.assertTrue(Path(str(source) + '-shm').exists())
                backup_database(source, backup)
                env = dict(os.environ)
                env['NEXUS_HUB_ACL_TEST_DIR'] = str(directory)
                script = r'''
$ErrorActionPreference='Stop'
$allowed=@([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value,'S-1-5-18','S-1-5-32-544')
$files=@(Get-ChildItem -LiteralPath $env:NEXUS_HUB_ACL_TEST_DIR -File -Force)
if ($files.Count -lt 4) { throw 'Missing fixture files' }
foreach ($file in $files) {
  $acl=Get-Acl -LiteralPath $file.FullName
  $rules=@($acl.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]))
  $found=@($rules | ForEach-Object { $_.IdentityReference.Value }) | Sort-Object -Unique
  if (Compare-Object ($allowed | Sort-Object -Unique) $found) { throw 'Missing or unexpected principal' }
  foreach ($rule in $rules) {
    if (-not $rule.IsInherited -or $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne 'FullControl') { throw 'Unexpected access' }
  }
}
'''
                result = subprocess.run(['pwsh.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                                        stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=15, check=False)
                self.assertEqual(result.returncode, 0)
            finally:
                writer.close()

if __name__ == '__main__':
    unittest.main()
