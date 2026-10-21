"""Portable authenticated encryption for small backup files; never reads deployment configuration."""

import argparse
import os
import stat
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

if __package__:
    from .local_files import new_descriptor, read_descriptor
else:
    from local_files import new_descriptor, read_descriptor

MAX_PLAINTEXT = 16 * 1024 * 1024
MAX_CIPHERTEXT = 24 * 1024 * 1024


class Parser(argparse.ArgumentParser):
    def error(self, message):
        super().error("Invalid arguments; details withheld")


def read_file(path: Path, limit: int) -> bytes:
    if path.is_symlink() or path.is_junction():
        raise ValueError("Input must be a regular file")
    with os.fdopen(read_descriptor(path), "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("Input must be a regular file")
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Input exceeds size limit")
    return data


def write_new(path: Path, data: bytes) -> None:
    with os.fdopen(new_descriptor(path), "wb") as destination:
        destination.write(data)
        destination.flush()
        os.fsync(destination.fileno())


def transform(source: Path, output: Path | None, key_file: Path, *, decrypt: bool) -> None:
    if output is None and not decrypt:
        raise ValueError("Encryption requires an output file")
    key = read_file(key_file, 44)
    if len(key) != 44:
        raise ValueError("Invalid key file")
    cipher = Fernet(key)
    data = read_file(source, MAX_CIPHERTEXT if decrypt else MAX_PLAINTEXT)
    result = cipher.decrypt(data) if decrypt else cipher.encrypt(data)
    if decrypt and len(result) > MAX_PLAINTEXT:
        raise ValueError("Plaintext exceeds size limit")
    if output is not None:
        write_new(output, result)


def main(argv=None) -> int:
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generator = commands.add_parser("keygen")
    generator.add_argument("--output", type=Path, required=True)
    for name in ("encrypt", "decrypt", "verify"):
        command = commands.add_parser(name)
        command.add_argument("source", type=Path)
        command.add_argument("--key-file", type=Path, required=True)
        if name == "verify":
            command.set_defaults(output=None)
        else:
            command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "keygen":
            write_new(args.output, Fernet.generate_key())
        else:
            transform(args.source, args.output, args.key_file, decrypt=args.command != "encrypt")
    except (OSError, ValueError, InvalidToken):
        print("Backup operation failed; input, key and filesystem details withheld", file=sys.stderr)
        return 1
    print("PASS: backup artifact authenticated" if args.command == "verify" else "PASS: new backup artifact created")
    return 0


if __name__ == "__main__":
    sys.exit(main())
