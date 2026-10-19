"""No-follow file handles for local tools with trusted parent directories."""

import os
import stat
from pathlib import Path


def new_descriptor(path: Path) -> int:
    if os.name != "nt":
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    return _windows_descriptor(path, read=False)


def read_descriptor(path: Path) -> int:
    if os.name != "nt":
        return os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    return _windows_descriptor(path, read=True)


def _windows_descriptor(path: Path, *, read: bool) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetFileType.argtypes = [wintypes.HANDLE]
    kernel.GetFileType.restype = wintypes.DWORD
    # CRT opens follow links; OPEN_REPARSE_POINT must protect both reads and exclusive creates.
    handle = create(os.path.abspath(path), 0x80000000 if read else 0x40000000,
                    1 if read else 0, None, 3 if read else 1, 0x80 | 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError("Cannot open local file")
    if kernel.GetFileType(handle) != 1:
        kernel.CloseHandle(handle)
        raise OSError("Local file must be a regular disk file")
    try:
        descriptor = msvcrt.open_osfhandle(handle, (os.O_RDONLY if read else os.O_WRONLY) | os.O_BINARY)
    except OSError:
        kernel.CloseHandle(handle)
        raise
    if read:
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError("Input must be a regular file without a reparse point")
        except OSError:
            os.close(descriptor)
            raise
    return descriptor
