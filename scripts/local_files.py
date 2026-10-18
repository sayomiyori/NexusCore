"""Exclusive output creation for local tools with trusted parent directories."""

import os
from pathlib import Path


def new_descriptor(path: Path) -> int:
    if os.name != "nt":
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
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
    # CRT O_EXCL follows dangling links on Windows; CREATE_NEW must open the reparse point itself.
    handle = create(os.path.abspath(path), 0x40000000, 0, None, 1, 0x80 | 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError("Cannot exclusively create output")
    if kernel.GetFileType(handle) != 1:
        kernel.CloseHandle(handle)
        raise OSError("Output must be a regular file")
    try:
        return msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
    except OSError:
        kernel.CloseHandle(handle)
        raise
