"""Test-only SQLite backup and restore; not for production paths."""
import os
import sqlite3
import stat
import tempfile
import time
from contextlib import closing
from pathlib import Path

from coordination_hub.store import Conflict, validate_schema


def backup_database(source, destination):
    """Make an exclusive, integrity-checked synthetic backup in the OS temp directory."""
    source = Path(source)
    destination = Path(destination)
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not source.is_absolute() or not destination.is_absolute():
        raise ValueError('Absolute paths required')
    if not source.parent.resolve().is_relative_to(temp_root) or not destination.parent.resolve().is_relative_to(temp_root):
        raise ValueError('Only temporary test files are supported')
    return _backup_database(source, destination)


def _backup_database(source, destination):
    source = Path(source)
    destination = Path(destination)
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Invalid source file')
    if destination.suffix != '.sqlite3':
        raise ValueError('Invalid backup destination')
    deadline = time.monotonic() + 10
    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError('Backup timed out')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=2)) as src:
        try:
            validate_schema(src)
        except Conflict:
            raise ValueError('Unknown source schema') from None
        fd, staging_name = tempfile.mkstemp(prefix='.hub-backup-', suffix='.sqlite3', dir=destination.parent)
        os.close(fd)
        staging = Path(staging_name)
        published = False
        staging_removed = True
        try:
            with closing(sqlite3.connect(staging, timeout=2)) as dst:
                src.backup(dst, pages=64, progress=progress, sleep=0.05)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Backup integrity check failed')
                try:
                    validate_schema(dst)
                except Conflict:
                    raise ValueError('Unknown backup schema') from None
            os.link(staging, destination)
            published = True
        finally:
            try:
                staging.unlink()
            except OSError:
                if not published:
                    raise
                staging_removed = False
        return {'published': True, 'staging_removed': staging_removed,
                'staging_path': None if staging_removed else str(staging)}
