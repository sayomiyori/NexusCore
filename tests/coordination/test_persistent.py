import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.name == 'nt', 'Windows ACL required')
class PersistentStorageTests(unittest.TestCase):
    def test_provision_refuses_directory_inside_git_tree(self):
        from coordination_hub.persistent import provision

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.git').mkdir()
            with self.assertRaises(ValueError):
                provision(root / 'private')
            self.assertFalse((root / 'private').exists())

    def test_provision_refuses_junction_in_parent(self):
        import subprocess

        from coordination_hub.persistent import provision

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / 'target'
            target.mkdir()
            link = root / 'link'
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                                    capture_output=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0)
            with self.assertRaises(ValueError):
                provision(link / 'private')
            self.assertFalse((target / 'private').exists())

    def test_live_path_does_not_trust_localappdata_environment(self):
        from coordination_hub.persistent import live_directory

        expected = live_directory()
        with patch.dict(os.environ, {'LOCALAPPDATA': 'D:/Programming/NexusCore'}):
            self.assertEqual(live_directory(), expected)

    def test_provision_backup_and_missing_database(self):
        from coordination_hub.persistent import backup, provision, provision_backup
        from coordination_hub.store import Store

        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'private'
            database = provision(directory)
            backup_directory = Path(folder) / 'backups'
            provision_backup(backup_directory)
            task = Store(database, existing_only=True).create_task('codex', 'Synthetic', 'Test')['id']
            snapshot = backup(directory, backup_directory)
            self.assertEqual(snapshot.parent, backup_directory)
            with closing(sqlite3.connect(snapshot.as_uri() + '?mode=ro', uri=True)) as connection:
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(connection.execute('SELECT id FROM tasks').fetchone()[0], task)
                with closing(sqlite3.connect(Path(folder) / 'restored.sqlite3')) as restored:
                    connection.backup(restored)
            self.assertEqual(Store(Path(folder) / 'restored.sqlite3', existing_only=True).get_task(task)['id'], task)
            with self.assertRaises(FileExistsError):
                provision(directory)
            database.unlink()
            with self.assertRaises(sqlite3.OperationalError):
                backup(directory)
            self.assertFalse(database.exists())

    def test_backup_rotates_only_recorded_verified_snapshots(self):
        from coordination_hub.persistent import backup, provision, provision_backup

        with tempfile.TemporaryDirectory() as folder:
            directory, backups = Path(folder) / 'private', Path(folder) / 'backups'
            provision(directory)
            provision_backup(backups)
            unrelated = backups / 'notes.txt'
            unrelated.write_text('preserve', encoding='utf-8')
            first = backup(directory, backups, keep=2)
            backup(directory, backups, keep=2)
            backup(directory, backups, keep=2)
            self.assertEqual(len(list(backups.glob('backup-*.sqlite3'))), 2)
            self.assertFalse(first.exists())
            self.assertEqual(unrelated.read_text(encoding='utf-8'), 'preserve')

    def test_unrecorded_backup_is_never_removed(self):
        import uuid

        from coordination_hub.persistent import backup, provision, provision_backup

        with tempfile.TemporaryDirectory() as folder:
            directory, backups = Path(folder) / 'private', Path(folder) / 'backups'
            provision(directory)
            provision_backup(backups)
            unrelated = backups / f'backup-{uuid.uuid4()}.sqlite3'
            unrelated.write_text('preserve', encoding='utf-8')
            with self.assertRaises(OSError):
                backup(directory, backups, keep=1)
            self.assertEqual(unrelated.read_text(encoding='utf-8'), 'preserve')

    def test_concurrent_backup_is_refused_while_locked(self):
        import subprocess
        import sys

        from coordination_hub.persistent import backup, provision, provision_backup

        with tempfile.TemporaryDirectory() as folder:
            directory, backups = Path(folder) / 'private', Path(folder) / 'backups'
            provision(directory)
            provision_backup(backups)
            code = ('import sys; from coordination_hub.persistent import _backup_lock; '
                    'guard=_backup_lock(sys.argv[1]); guard.__enter__(); print("ready",flush=True); input(); '
                    'guard.__exit__(None,None,None)')
            process = subprocess.Popen([sys.executable, '-B', '-c', code, str(backups)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'ready')
                with self.assertRaises(OSError):
                    backup(directory, backups, keep=1)
            finally:
                process.communicate('\n', timeout=10)
            self.assertTrue(backup(directory, backups, keep=1).exists())
