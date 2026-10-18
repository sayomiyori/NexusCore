"""Portable authenticated encryption for small backup files; never reads deployment configuration."""

import argparse
import os
import stat
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

MAX_PLAINTEXT = 16 * 1024 * 1024
MAX_CIPHERTEXT = 24 * 1024 * 1024


class Parser(argparse.ArgumentParser):
    def error(self, message):
        super().error("Invalid arguments; details withheld")


def read_file(path: Path, limit: int) -> bytes:
    if path.is_symlink() or path.is_junction():
        raise ValueError("Input must be a regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("Input must be a regular file")
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Input exceeds size limit")
    return data


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
    # CRT O_EXCL follows dangling links on Windows; CREATE_NEW must open the reparse point itself.
    handle = create(os.path.abspath(path), 0x40000000, 0, None, 1, 0x80 | 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError("Cannot exclusively create output")
    try:
        return msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
    except OSError:
        kernel.CloseHandle(handle)
        raise


def write_new(path: Path, data: bytes) -> None:
    with os.fdopen(new_descriptor(path), "wb") as destination:
        destination.write(data)
        destination.flush()
        os.fsync(destination.fileno())


def transform(source: Path, output: Path, key_file: Path, *, decrypt: bool) -> None:
    key = read_file(key_file, 44)
    if len(key) != 44:
        raise ValueError("Invalid key file")
    cipher = Fernet(key)
    data = read_file(source, MAX_CIPHERTEXT if decrypt else MAX_PLAINTEXT)
    result = cipher.decrypt(data) if decrypt else cipher.encrypt(data)
    if decrypt and len(result) > MAX_PLAINTEXT:
        raise ValueError("Plaintext exceeds size limit")
    write_new(output, result)


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generator = commands.add_parser("keygen")
    generator.add_argument("--output", type=Path, required=True)
    for name in ("encrypt", "decrypt"):
        command = commands.add_parser(name)
        command.add_argument("source", type=Path)
        command.add_argument("--key-file", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "keygen":
            write_new(args.output, Fernet.generate_key())
        else:
            transform(args.source, args.output, args.key_file, decrypt=args.command == "decrypt")
    except (OSError, ValueError, InvalidToken):
        print("Backup operation failed; input, key and filesystem details withheld", file=sys.stderr)
        return 1
    print("PASS: new backup artifact created")
    return 0


if __name__ == "__main__":
    sys.exit(main())
