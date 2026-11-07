"""Emit a task-local OpenCode configuration for the coordination Hub.

The tool is read-only: it validates the agent, the agent's registered worktree
and the Hub database, then prints the ``mcp.servers.nexus_hub`` entry to stdout.
The emitted server entry point comes from the validated agent worktree, not from
this tool's own checkout, so a profile cannot execute another worktree's Hub
code. The tool never writes a configuration file, never edits a global profile
and never opens the database read-write. Diagnostics are static so a failure
cannot echo user arguments, environment values or database content.
"""
import argparse
import json
import sqlite3
import stat
import sys
import tempfile
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coordination_hub.identity import (
    IdentityError,
    repository_root,
    verify_configured_path,
    verify_worktree,
    worktree_for,
)
from coordination_hub.paths import live_directory
from coordination_hub.store import Conflict, validate_schema

# Roles that use the Hub through OpenCode. The reviewer role is intentionally
# excluded: it reviews submissions and does not reserve work of its own.
ROLES = ('security', 'development')
SYNTHETIC_DATABASE = Path('D:/Programming/NexusCore-coordination-connectivity-test/hub.sqlite3')

MESSAGES = {
    'arguments': 'invalid arguments',
    'database_path': 'unsupported database path',
    'database_link': 'database path is linked',
    'database_missing': 'database not found',
    'database_unreadable': 'database cannot be read',
    'database_schema': 'database schema mismatch',
    'runtime': 'runtime unavailable',
    'worktree': 'agent worktree unavailable',
}


class ProfileError(Exception):
    """A validation failure with a fixed, non-reflective diagnostic."""


def database_path(database=None):
    """Return the accepted Hub database path, mirroring the server's policy.

    Only the live Hub path, a temporary ``hub.sqlite3`` and the synthetic
    connectivity database are accepted. The checks run at emission time; the
    server re-reads the same state when it starts, so this is a preflight and
    not an atomic guarantee.
    """
    candidate = Path(database) if database is not None else live_directory() / 'hub.sqlite3'
    absolute = candidate.absolute()
    if absolute == (live_directory() / 'hub.sqlite3'):
        return absolute
    if absolute == SYNTHETIC_DATABASE:
        return absolute
    if absolute.name == 'hub.sqlite3' and absolute.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        return absolute
    raise ProfileError(MESSAGES['database_path'])


def verify_database(database):
    """Check the database without writing: no links, regular file, server schema.

    The schema comes from store.validate_schema on a read-only connection, so a
    database with the expected application id and version but unrelated tables
    or triggers is rejected instead of being trusted.
    """
    try:
        verify_configured_path(database)
    except IdentityError as exc:
        raise ProfileError(MESSAGES['database_link']) from exc
    try:
        info = database.lstat()
    except OSError as exc:
        raise ProfileError(MESSAGES['database_missing']) from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ProfileError(MESSAGES['database_missing'])
    target = database.as_uri() + '?mode=ro'
    try:
        with closing(sqlite3.connect(target, uri=True, timeout=5)) as db:
            db.execute('PRAGMA busy_timeout = 5000')
            validate_schema(db)
    except Conflict as exc:
        raise ProfileError(MESSAGES['database_schema']) from exc
    except sqlite3.Error as exc:
        raise ProfileError(MESSAGES['database_unreadable']) from exc
    return database


def runtime_paths(worktree):
    """Return the interpreter and the validated worktree's server entry point.

    The server is taken from the agent worktree that was just verified, not from
    the checkout this tool was run from. ``--agent`` therefore selects the Hub
    identity, its worktree and the Hub code that will execute for it. The target
    worktree may be dirty or stale: pinning the entry point only prevents running
    another worktree's Hub code, it is not source-integrity assurance. Linked,
    reparse-point or non-regular server paths fail closed like the database path.
    """
    interpreter = Path(sys.executable)
    server = Path(worktree) / 'coordination_hub' / 'server.py'
    try:
        verify_configured_path(server)
    except IdentityError as exc:
        raise ProfileError(MESSAGES['runtime']) from exc
    if not interpreter.is_file() or not server.is_file():
        raise ProfileError(MESSAGES['runtime'])
    return str(interpreter), str(server)


def build_config(agent, database=None):
    """Return the OpenCode configuration object for one agent and database."""
    if agent not in ROLES:
        raise ProfileError(MESSAGES['arguments'])
    database = verify_database(database_path(database))
    worktree = worktree_for('nexuscore', agent)
    try:
        verify_worktree(repository_root('nexuscore'), agent, worktree)
    except IdentityError as exc:
        raise ProfileError(MESSAGES['worktree']) from exc
    interpreter, server = runtime_paths(worktree)
    command = [interpreter, server, agent, str(database), str(worktree)]
    return {'mcp': {'servers': {'nexus_hub': {'type': 'local', 'command': command,
                                              'disabled': False}}}}


class _Parser(argparse.ArgumentParser):
    """Argument parser whose failures never echo what the caller typed."""

    def error(self, message):
        self.exit(2, f"error: {MESSAGES['arguments']}\n")


def main(argv=None):
    parser = _Parser(description='Print the task-local OpenCode Hub configuration.',
                     add_help=True)
    parser.add_argument('--agent', required=True, choices=ROLES,
                        help='agent role that will use the configuration')
    parser.add_argument('--database', default=None,
                        help='Hub database; defaults to the live Hub database')
    options = parser.parse_args(argv)
    try:
        config = build_config(options.agent, options.database)
    except ProfileError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(config, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
