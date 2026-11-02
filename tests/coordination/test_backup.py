import importlib.util
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'coordination_hub' / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class BackupTests(unittest.TestCase):
    def test_published_backup_reports_cleanup_failure_without_ambiguous_result(self):
        store = load('coordination_backup_store_cleanup', 'store.py')
        backup = load('coordination_backup_cleanup', 'backup.py')
        with tempfile.TemporaryDirectory() as folder:
            source, destination = Path(folder) / 'hub.sqlite3', Path(folder) / 'backup.sqlite3'
            store.Store(source)
            with patch.object(Path, 'unlink', side_effect=PermissionError('synthetic')):
                result = backup.backup_database(source, destination)
            self.assertTrue(destination.exists())
            self.assertTrue(result['published'])
            self.assertFalse(result['staging_removed'])
            self.assertTrue(Path(result['staging_path']).exists())

    def test_backup_refuses_unrelated_database_with_forged_markers(self):
        backup = load('coordination_backup_forged', 'backup.py')
        with tempfile.TemporaryDirectory() as folder:
            source, destination = Path(folder) / 'fake.sqlite3', Path(folder) / 'backup.sqlite3'
            with closing(sqlite3.connect(source)) as db:
                db.execute('CREATE TABLE unrelated (value TEXT)')
                db.execute('PRAGMA application_id=1314419522')
                db.execute('PRAGMA user_version=4')
            with self.assertRaises(ValueError):
                backup.backup_database(source, destination)
            self.assertFalse(destination.exists())

    def test_failed_backup_leaves_no_destination_or_staging_file(self):
        backup = load('coordination_backup_invalid', 'backup.py')
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source, destination = folder / 'bad.sqlite3', folder / 'backup.sqlite3'
            source.write_text('not a database', encoding='utf-8')
            with self.assertRaises(sqlite3.DatabaseError):
                backup.backup_database(source, destination)
            self.assertFalse(destination.exists())
            self.assertEqual([entry.name for entry in folder.iterdir()], ['bad.sqlite3'])

    def test_backup_includes_committed_wal_data(self):
        store = load('coordination_backup_store_wal', 'store.py')
        backup = load('coordination_backup_wal', 'backup.py')
        with tempfile.TemporaryDirectory() as folder:
            source, copy = Path(folder) / 'hub.sqlite3', Path(folder) / 'copy.sqlite3'
            store.Store(source)
            with closing(sqlite3.connect(source)) as writer:
                self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower(), 'wal')
                writer.execute('PRAGMA wal_autocheckpoint=0')
                writer.execute("INSERT INTO messages VALUES ('test-id','security','codex','Synthetic',1)")
                writer.commit()
                self.assertTrue(Path(str(source) + '-wal').exists())
                backup.backup_database(source, copy)
                with closing(sqlite3.connect(copy)) as restored:
                    self.assertEqual(restored.execute('SELECT body FROM messages').fetchone()[0], 'Synthetic')

    def test_backup_restore_and_no_overwrite(self):
        store = load('coordination_backup_store', 'store.py')
        backup = load('coordination_backup', 'backup.py')
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source, copy, restored = (folder / name for name in ('hub.sqlite3', 'copy.sqlite3', 'restored.sqlite3'))
            hub = store.Store(source)
            task = hub.create_task('codex', 'Synthetic backup', 'Synthetic data')
            backup.backup_database(source, copy)
            backup.backup_database(copy, restored)
            with closing(sqlite3.connect(restored)) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('SELECT id FROM tasks').fetchone()[0], task['id'])
            before = copy.read_bytes()
            with self.assertRaises(FileExistsError):
                backup.backup_database(source, copy)
            self.assertEqual(copy.read_bytes(), before)

if __name__ == '__main__':
    unittest.main()
