"""Read-only checks for the configured agent worktrees of allowlisted repositories."""
import ntpath
import os
import re
import stat
import subprocess
from pathlib import Path

BRANCHES = {'security': 'agent/security', 'development': 'agent/development', 'codex': 'agent/codex'}
# Repository ids exposed over MCP. Keys must stay in sync with store.REPOSITORIES;
# a repository with no configured root can never produce verified review evidence.
REPOSITORY_ROOTS = {
    'nexuscore': Path('D:/Programming/NexusCore'),
    'authfortress': Path('D:/Programming/AuthFortress'),
}
GIT = Path('C:/Program Files/Git/cmd/git.exe')

class IdentityError(Exception):
    pass

def repository_root(repository):
    """Return the fixed root of an allowlisted repository, rejecting anything else."""
    root = REPOSITORY_ROOTS.get(repository)
    if root is None:
        raise IdentityError('Unsupported repository')
    return root

def worktree_for(repository, agent):
    """Return the single accepted worktree location for an agent in a repository.

    The layout is fixed by convention, not by the caller: <root>/.worktrees/<agent>.
    """
    root = repository_root(repository)
    if agent not in BRANCHES:
        raise IdentityError('Invalid agent')
    return root / '.worktrees' / agent

def _git(directory, args):
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0'})
    return subprocess.run([str(GIT), '-C', str(directory), '-c', 'core.fsmonitor=false', *args],
                          env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=5, check=True).stdout

def verify_no_links(root, relative):
    """Reject existing links and Windows reparse points in a relative file path."""
    root = Path(root)
    parts = relative.split('/')
    if not parts or any(part in ('', '.', '..') or '\\' in part or ':' in part for part in parts):
        raise IdentityError('Invalid path')
    current = root
    for part in parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise IdentityError('Cannot verify path') from exc
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise IdentityError('Links are not supported')
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise IdentityError('Hard links are not supported')

def verify_configured_path(path):
    """Reject links and reparse points on a configured absolute path before resolving it.

    Resolving first would silently follow a symlinked or junctioned configured
    root, so every existing component from the drive anchor is checked as it is
    stored on disk.
    """
    path = Path(path)
    if not path.is_absolute() or not path.anchor:
        raise IdentityError('Invalid configured path')
    verify_no_links(Path(path.anchor), '/'.join(path.parts[1:]))

def verify_worktree(root, agent, worktree, repository='nexuscore'):
    """Check an explicitly configured agent/location against Git's worktree registry.

    This detects configuration mistakes, stale checkouts and foreign paths, not
    impersonation by the same OS user. The repository must be allowlisted, the
    root must be that repository's fixed root, and the worktree must be the
    registered <root>/.worktrees/<agent> on branch refs/heads/agent/<agent>.
    Other agents' registry entries are matched by name only, so a stale or
    missing entry of another agent never blocks the caller.
    """
    if agent not in BRANCHES:
        raise IdentityError('Invalid agent')
    expected_root = repository_root(repository)
    try:
        if os.path.normcase(os.path.abspath(root)) != os.path.normcase(os.path.abspath(expected_root)):
            raise IdentityError('Repository root mismatch')
        expected_input = worktree_for(repository, agent)
        if os.path.normcase(os.path.abspath(worktree)) != os.path.normcase(os.path.abspath(expected_input)):
            raise IdentityError('Worktree mismatch')
        # Check the configured path as stored, before any resolve follows a link.
        verify_configured_path(expected_input)
        expected = expected_input.resolve(strict=True)
        actual = Path(worktree).resolve(strict=True)
        if actual != expected:
            raise IdentityError('Worktree mismatch')
        entries = _git(expected_root.resolve(strict=True), ['worktree', 'list', '--porcelain', '-z']).decode('utf-8', errors='strict').split('\0\0')
        matches = 0
        for entry in entries:
            values = entry.split('\0')
            paths = [line[9:] for line in values if line.startswith('worktree ')]
            branches = [line[7:] for line in values if line.startswith('branch ')]
            if len(paths) != 1 or ntpath.normcase(ntpath.normpath(paths[0])) != ntpath.normcase(str(expected_input)):
                # Entries of other agents are never resolved: a stale registration
                # of an unrelated worktree must not abort this verification.
                continue
            if branches != ['refs/heads/' + BRANCHES[agent]]:
                raise IdentityError('Worktree branch mismatch')
            matches += 1
        if matches != 1:
            raise IdentityError('Worktree not registered')
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        raise IdentityError('Cannot verify worktree') from exc

def verify_revision(root, agent, worktree, repository, revision):
    """Require a clean configured worktree of the submitted repository at the submitted full commit ID."""
    if repository not in REPOSITORY_ROOTS or not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision):
        raise IdentityError('Unsupported repository or revision')
    verify_worktree(root, agent, worktree, repository)
    try:
        head = _git(worktree, ['rev-parse', '--verify', 'HEAD^{commit}']).decode('ascii').strip()
        status = _git(worktree, ['status', '--porcelain=v1', '--untracked-files=all'])
        if head != revision or status:
            raise IdentityError('Commit or worktree changed')
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise IdentityError('Cannot verify revision') from exc

def verify_submission(agent, repository, revision):
    """Verify the submitting agent's own worktree in the submitted repository.

    A repository whose worktree for this agent is missing, foreign, on the wrong
    branch, dirty or not at the submitted commit fails closed.
    """
    root = repository_root(repository)
    verify_revision(root, agent, worktree_for(repository, agent), repository, revision)

def verify_reservation_scope(agent, repository):
    """Verify the reserving agent's own worktree before leasing paths in a repository.

    Other agents may legitimately have no worktree in that repository, so their
    absence is not checked here; only the caller's own assignment is required.
    Returns the repository root for the caller's link checks.
    """
    root = repository_root(repository)
    verify_worktree(root, agent, worktree_for(repository, agent), repository)
    return root
