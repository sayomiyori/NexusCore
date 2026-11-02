import importlib.util
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / 'coordination_hub' / 'directory_guard.py'

@unittest.skipUnless(os.name == 'nt', 'Windows directory handle required')
class DirectoryGuardTests(unittest.TestCase):
    def test_directory_cannot_be_renamed_while_pinned(self):
        self.assertTrue(MODULE.exists(), 'Directory guard must exist')
        spec = importlib.util.spec_from_file_location('guard', MODULE)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'guarded'
            moved = Path(folder) / 'moved'
            path.mkdir()
            with guard.test_directory_guard(path):
                with self.assertRaises(OSError):
                    os.rename(path, moved)
                (path / 'synthetic.txt').write_text('test', encoding='utf-8')
            os.rename(path, moved)
            self.assertTrue((moved / 'synthetic.txt').exists())

    def test_junction_is_refused(self):
        self.assertTrue(MODULE.exists(), 'Directory guard must exist')
        spec = importlib.util.spec_from_file_location('guard2', MODULE)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'target'
            link = Path(folder) / 'link'
            target.mkdir()
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                    capture_output=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0)
            with self.assertRaises(OSError), guard.test_directory_guard(link):
                self.fail('Junction must not be accepted')

    def test_parent_cannot_be_renamed_while_child_is_pinned(self):
        self.assertTrue(MODULE.exists(), 'Directory guard must exist')
        spec = importlib.util.spec_from_file_location('guard3', MODULE)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder) / 'parent'
            directory = parent / 'child'
            parent.mkdir()
            directory.mkdir()
            with guard.test_directory_guard(directory), self.assertRaises(OSError):
                os.rename(parent, Path(folder) / 'moved')

    def test_two_processes_pin_directory_while_sqlite_writes(self):
        spec = importlib.util.spec_from_file_location('guard4', MODULE)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        code = '''import importlib.util,sys
spec=importlib.util.spec_from_file_location('guard',sys.argv[1]); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
with m.test_directory_guard(sys.argv[2]):
    print('ready',flush=True); input()
'''
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'guarded'
            directory.mkdir()
            process = subprocess.Popen([sys.executable, '-B', '-c', code, str(MODULE), str(directory)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'ready')
                with guard.test_directory_guard(directory):
                    with self.assertRaises(OSError):
                        os.rename(directory, Path(folder) / 'moved')
                    db = sqlite3.connect(directory / 'hub.sqlite3')
                    try:
                        self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower(), 'wal')
                        db.execute('CREATE TABLE synthetic (n INTEGER)')
                        db.execute('INSERT INTO synthetic VALUES (1)')
                        db.commit()
                    finally:
                        db.close()
                process.stdin.write('\n')
                process.stdin.flush()
                _, errors = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, errors)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

if __name__ == '__main__':
    unittest.main()
