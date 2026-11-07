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

def _git_environment():
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0'})
    return env

def _probe_environment():
    """Environment for reading the effective user line-ending configuration.

    GIT_* variables are dropped so a caller cannot spoof or suppress the setting,
    while the system, global and local configuration files stay visible.
    """
    return {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}

def _eol_overrides(directory):
    """Return the effective core.autocrlf setting as ``-c`` arguments.

    The verification environment ignores system and user Git configuration for
    deterministic behavior, but the worktree was checked out with the user's line
    ending settings. Re-applying this single validated scalar keeps a CRLF checkout
    from looking modified against its LF index once the index stat cache is
    invalidated, without trusting any other user configuration. A failed lookup or
    an unrecognized value adds no override, so the stricter comparison fails closed.
    """
    try:
        completed = subprocess.run([str(GIT), '-C', str(directory), 'config', '--get', 'core.autocrlf'],
                                   env=_probe_environment(), stdin=subprocess.DEVNULL,
                                   capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    value = completed.stdout.decode('ascii', errors='replace').strip().lower()
    normalized = {'true': 'true', 'yes': 'true', 'on': 'true', '1': 'true',
                  'false': 'false', 'no': 'false', 'off': 'false', '0': 'false',
                  'input': 'input'}.get(value)
    if completed.returncode == 0 and normalized:
        return ['-c', 'core.autocrlf=' + normalized]
    return []

def _git(directory, args, line_endings=False):
    extra = _eol_overrides(directory) if line_endings else []
    return subprocess.run([str(GIT), '-C', str(directory), '-c', 'core.fsmonitor=false',
                           *extra, *args],
                          env=_git_environment(), stdin=subprocess.DEVNULL, capture_output=True,
                          timeout=5, check=True).stdout

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
        status = _git(worktree, ['status', '--porcelain=v1', '--untracked-files=all'],
                      line_endings=True)
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
