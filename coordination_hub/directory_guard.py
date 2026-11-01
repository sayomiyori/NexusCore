"""Windows directory pinning for temporary fixtures and the local Hub."""
import ctypes
import os
import tempfile
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path

from coordination_hub.paths import live_directory


class _Attributes(ctypes.Structure):
    _fields_ = [('attributes', wintypes.DWORD), ('reparse_tag', wintypes.DWORD)]

@contextmanager
def test_directory_guard(directory):
    """Pin an allowed directory against deletion and reject its reparse point."""
    if os.name != 'nt':
        raise OSError('Windows only')
    path = Path(directory)
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    live_path = live_directory()
    backup_path = Path('D:/NexusCoreCoordinationBackups')
    if not path.is_absolute() or not (path.parent.resolve(strict=True).is_relative_to(temp_root)
                                      or path in (live_path, backup_path)):
        raise ValueError('Directory is not allowed')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    get_info = kernel.GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x81, 3, None, 3, 0x02000000 | 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), 'Cannot open guarded directory', str(path))
    try:
        info = _Attributes()
        if not get_info(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError('Cannot inspect test directory')
        if info.attributes & 0x400 or not info.attributes & 0x10:
            raise OSError('Reparse point or non-directory is not supported')
        yield
    finally:
        close(handle)
