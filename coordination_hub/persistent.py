"""Provision and back up a dedicated Windows Hub directory for trusted local agents."""
import ctypes
import hashlib
import os
import sqlite3
import stat
import subprocess
import tempfile
import uuid
from contextlib import ExitStack, contextmanager
from ctypes import wintypes
from pathlib import Path

from coordination_hub.backup import _backup_database
from coordination_hub.directory_guard import test_directory_guard
from coordination_hub.identity import IdentityError, verify_no_links
from coordination_hub.paths import live_directory
from coordination_hub.store import Store

CREATE_ACL = r"""
$ErrorActionPreference = 'Stop'
$path = $env:NEXUS_HUB_DIRECTORY
if (Test-Path -LiteralPath $path) { throw 'Directory already exists' }
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = [System.Security.AccessControl.DirectorySecurity]::new()
$acl.SetOwner($user)
$acl.SetAccessRuleProtection($true, $false)
$inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
foreach ($sid in @($user, [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18'), [System.Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))) {
  $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new($sid, [System.Security.AccessControl.FileSystemRights]::FullControl, $inherit, [System.Security.AccessControl.PropagationFlags]::None, [System.Security.AccessControl.AccessControlType]::Allow))
}
[System.IO.FileSystemAclExtensions]::Create([System.IO.DirectoryInfo]::new($path), $acl)
"""

VERIFY_ACL = r"""
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $env:NEXUS_HUB_DIRECTORY
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if (-not $acl.AreAccessRulesProtected -or $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $user) { throw 'Unexpected ACL owner or inheritance' }
$expected = @($user, 'S-1-5-18', 'S-1-5-32-544') | Sort-Object -Unique
$rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))
$found = @($rules | ForEach-Object { $_.IdentityReference.Value }) | Sort-Object -Unique
if (Compare-Object $expected $found) { throw 'Unexpected ACL principals' }
$inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
foreach ($rule in $rules) {
  if ($rule.IsInherited -or $rule.AccessControlType -ne 'Allow' -or $rule.FileSystemRights -ne 'FullControl' -or $rule.InheritanceFlags -ne $inherit -or $rule.PropagationFlags -ne 'None') { throw 'Unexpected ACL rule' }
}
"""


def _directory(path, *, backups=False):
    path = Path(path)
    if os.name != 'nt' or not path.is_absolute():
        raise ValueError('An absolute Windows directory is required')
    live = Path('D:/NexusCoreCoordinationBackups') if backups else live_directory()
    temp = Path(tempfile.gettempdir()).resolve(strict=True)
    if path != live and not path.parent.resolve(strict=True).is_relative_to(temp):
        raise ValueError('Directory is not allowed')
    try:
        verify_no_links(Path(path.anchor), '/'.join(path.parts[1:]))
    except IdentityError:
        raise ValueError('Linked directories are not allowed') from None
    if any((parent / '.git').exists() for parent in (path, *path.parents)):
        raise ValueError('Hub must be outside Git')
    return path


def _powershell(path, script):
    env = dict(os.environ)
    env['NEXUS_HUB_DIRECTORY'] = str(path)
    pwsh = 'C:/Users/flamx/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe'
    result = subprocess.run([pwsh, '-NoProfile', '-NonInteractive', '-Command', script],
                            env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=20, check=False)
    if result.returncode:
        raise OSError('Directory security operation failed')


def provision(path):
    """Initialize an empty dedicated directory; never overwrite existing data."""
    path = _directory(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError('Hub directory already exists')
    _powershell(path, CREATE_ACL)
    with test_directory_guard(path):
        _powershell(path, VERIFY_ACL)
        database = path / 'hub.sqlite3'
        with database.open('xb'):
            pass
        Store(database)
        Store(database, existing_only=True)
        return database


def provision_backup(path):
    """Create a separate private backup directory without replacing existing data."""
    path = _directory(path, backups=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError('Backup directory already exists')
    _powershell(path, CREATE_ACL)
    with test_directory_guard(path):
        _powershell(path, VERIFY_ACL)
    return path


def verify_runtime(path):
    """Verify ACL and existing SQLite files while the caller pins the directory."""
    path = _directory(path)
    _powershell(path, VERIFY_ACL)
    for name in ('hub.sqlite3', 'hub.sqlite3-wal', 'hub.sqlite3-shm', 'hub.sqlite3-journal'):
        try:
            info = (path / name).lstat()
        except FileNotFoundError:
            if name == 'hub.sqlite3':
                raise sqlite3.OperationalError('Hub database is missing') from None
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Invalid database file')


@contextmanager
def _backup_lock(directory):
    """Allow at most one backup process in the dedicated directory."""
    lock = Path(directory) / '.hub-backup.lock'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    handle = create(str(lock), 0x80000000 | 0x40000000, 0, None, 4, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError('Backup already running or lock unavailable')
    try:
        info = lock.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise OSError('Invalid backup lock')
        yield
    finally:
        close(handle)


def backup(path, backup_directory=None, *, keep=30):
    """Create a verified backup and rotate only matching recorded snapshots."""
    if type(keep) is not int or not 1 <= keep <= 365:
        raise ValueError('Invalid backup retention')
    path = _directory(path)
    backup_directory = path if backup_directory is None else _directory(backup_directory, backups=True)
    with ExitStack() as stack:
        stack.enter_context(test_directory_guard(path))
        if backup_directory != path:
            stack.enter_context(test_directory_guard(backup_directory))
            _powershell(backup_directory, VERIFY_ACL)
        stack.enter_context(_backup_lock(backup_directory))
        verify_runtime(path)
        database = path / 'hub.sqlite3'
        try:
            info = database.lstat()
        except FileNotFoundError:
            raise sqlite3.OperationalError('Hub database is missing') from None
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Invalid database file')
        snapshots = list(backup_directory.glob('backup-*.sqlite3'))
        markers = list(backup_directory.glob('backup-*.sha256'))
        if list(backup_directory.glob('.hub-backup-*.sqlite3')) or len(snapshots) != len(markers):
            raise OSError('Unrecorded backup data requires inspection')
        recorded = []
        for snapshot in snapshots:
            marker = snapshot.with_suffix('.sha256')
            try:
                identifier = snapshot.stem.removeprefix('backup-')
                info, marker_info = snapshot.lstat(), marker.lstat()
                if (str(uuid.UUID(identifier)) != identifier or not stat.S_ISREG(info.st_mode)
                        or not stat.S_ISREG(marker_info.st_mode) or info.st_nlink != 1 or marker_info.st_nlink != 1
                        or getattr(info, 'st_file_attributes', 0) & 0x400
                        or getattr(marker_info, 'st_file_attributes', 0) & 0x400):
                    raise ValueError
                digest = marker.read_text(encoding='ascii').strip()
                with snapshot.open('rb') as source:
                    if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
                        raise ValueError
                recorded.append((info.st_mtime_ns, snapshot.name, snapshot, marker, digest))
            except (OSError, UnicodeError, ValueError):
                raise OSError('Unverified backup data requires inspection') from None
        destination = backup_directory / f'backup-{uuid.uuid4()}.sqlite3'
        result = _backup_database(database, destination)
        if not result['staging_removed']:
            raise OSError('Backup published but staging cleanup failed')
        with destination.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        marker = destination.with_suffix('.sha256')
        with marker.open('x', encoding='ascii') as output:
            output.write(digest + '\n')
            output.flush()
            os.fsync(output.fileno())
        recorded.sort(reverse=True)
        for _, _, snapshot, marker, expected in recorded[keep - 1:]:
            with snapshot.open('rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
                    raise OSError('Backup changed during retention')
            snapshot.unlink()
            marker.unlink()
        return destination


if __name__ == '__main__':
    import sys

    if sys.argv[1:] != ['backup']:
        raise SystemExit('Usage: python -m coordination_hub.persistent backup')
    print(backup(live_directory(), Path('D:/NexusCoreCoordinationBackups')))
