"""Disposable Git repositories and a runpy injection wrapper for the Hub tests.

Every repository used through this module exists only inside a temporary
directory. The injection wrapper runs the real server with
``identity.REPOSITORY_ROOTS`` replaced by an explicitly supplied mapping, so the
full tool flow can be exercised without depending on any real agent worktree
being present or clean. The production allowlist in ``identity.py`` stays fixed;
nothing here is environment-configurable.

The mapping is replaced, never patched, so a repository the caller does not map
is absent in the child process and ``repository_root`` raises instead of silently
inheriting a production checkout. The wrapper also refuses to start when the
mapping does not cover exactly the allowlisted ids, when a root is blank or
relative, or when a root resolves to a repository's production path. An omission
and an explicit ``D:/Programming/WebHook_Manager`` literal therefore both fail
closed; a filesystem alias such as a junction is still rejected downstream by the
identity link checks.

An optional live-directory root patches ``coordination_hub.paths.live_directory``
before the server starts, which lets the live-database startup tests run against
a provisioned temporary directory instead of the real coordination directory.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

GIT = 'C:/Program Files/Git/cmd/git.exe'
AGENTS = ('security', 'development', 'codex')

# sys.argv layout for
# `python -c INJECTION <server> <agent> <database> <worktree> <roots> <live_root>`.
# roots is a JSON object with one disposable root per allowlisted repository;
# live_root is empty unless the caller injects a provisioned live directory.
INJECTION = '''import json, os, runpy, sys
from pathlib import Path
server, agent, database, worktree, roots, live_root = sys.argv[1:7]
sys.path.insert(0, str(Path(server).parent))
import identity
raw = json.loads(roots)
if not isinstance(raw, dict):
    raise SystemExit('injected roots must be a JSON object')
blank = [name for name, value in raw.items()
         if not isinstance(value, str) or not value.strip()]
if blank:
    raise SystemExit('injected roots must be non-blank strings: '
                     + ', '.join(sorted(blank)))
relative = [name for name, value in raw.items() if not Path(value).is_absolute()]
if relative:
    raise SystemExit('injected roots must be absolute paths: '
                     + ', '.join(sorted(relative)))
mapping = {name: Path(value) for name, value in raw.items()}
if set(mapping) != set(identity.REPOSITORY_ROOTS):
    raise SystemExit('injected roots must cover exactly: '
                     + ', '.join(sorted(identity.REPOSITORY_ROOTS)))
def _key(path):
    return os.path.normcase(os.path.normpath(str(path)))
# Production paths are compared as fixed literals and never resolved, so a
# fixture check cannot even stat the real checkout. The caller's root is
# resolved, so a short name, junction or trailing-dot spelling still matches.
production = [name for name in mapping
              if _key(mapping[name]) == _key(identity.REPOSITORY_ROOTS[name])
              or os.path.normcase(os.path.realpath(os.path.abspath(str(mapping[name]))))
              == _key(identity.REPOSITORY_ROOTS[name])]
if production:
    raise SystemExit('injected roots must not be production paths: '
                     + ', '.join(sorted(production)))
identity.REPOSITORY_ROOTS.clear()
identity.REPOSITORY_ROOTS.update(mapping)
if live_root:
    sys.path.insert(0, str(Path(server).resolve().parent.parent))
    import coordination_hub.paths as paths
    paths.live_directory = lambda: Path(live_root)
sys.argv = [server, agent, database, worktree]
runpy.run_path(server, run_name='__main__')
'''


def repository_roots(nexus_root, auth_root, webhook_root):
    """JSON mapping of disposable roots, one explicit entry per allowlisted repository.

    A missing, blank or non-string root is rejected here as well as in the child
    process, so no caller can leave a repository pointing at its real checkout by
    omission.
    """
    roots = {'nexuscore': nexus_root, 'authfortress': auth_root,
             'webhook_manager': webhook_root}
    missing = [name for name, value in roots.items()
               if not isinstance(value, (str, os.PathLike)) or not str(value).strip()]
    if missing:
        raise ValueError('disposable root required for: ' + ', '.join(missing))
    return json.dumps({name: str(Path(value)) for name, value in roots.items()})


def load(module_name, path):
    """Load a module by path, so tests never depend on the current package layout."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def injected_command(server, agent, database, worktree, nexus_root, auth_root, webhook_root,
                     live_root=''):
    """Arguments for the stdio server with disposable repository roots injected."""
    return ['-B', '-c', INJECTION, str(server), agent, str(database), str(worktree),
            repository_roots(nexus_root, auth_root, webhook_root), str(live_root)]


def injected_parameters(server, agent, database, worktree, nexus_root, auth_root, webhook_root,
                        live_root=''):
    from mcp import StdioServerParameters
    return StdioServerParameters(
        command=sys.executable,
        args=injected_command(server, agent, database, worktree, nexus_root, auth_root,
                              webhook_root, live_root))


# sys.argv layout for
# `python -c PROFILE_INJECTION <tool> <roots> <tool arguments...>`.
PROFILE_INJECTION = '''import json, os, runpy, sys
from pathlib import Path
tool, roots = sys.argv[1:3]
sys.path.insert(0, str(Path(tool).resolve().parent.parent))
import coordination_hub.identity as identity
raw = json.loads(roots)
if not isinstance(raw, dict):
    raise SystemExit('injected roots must be a JSON object')
blank = [name for name, value in raw.items()
         if not isinstance(value, str) or not value.strip()]
if blank:
    raise SystemExit('injected roots must be non-blank strings: '
                     + ', '.join(sorted(blank)))
relative = [name for name, value in raw.items() if not Path(value).is_absolute()]
if relative:
    raise SystemExit('injected roots must be absolute paths: '
                     + ', '.join(sorted(relative)))
mapping = {name: Path(value) for name, value in raw.items()}
if set(mapping) != set(identity.REPOSITORY_ROOTS):
    raise SystemExit('injected roots must cover exactly: '
                     + ', '.join(sorted(identity.REPOSITORY_ROOTS)))
def _key(path):
    return os.path.normcase(os.path.normpath(str(path)))
# Production paths are compared as fixed literals and never resolved, so a
# fixture check cannot even stat the real checkout. The caller's root is
# resolved, so a short name, junction or trailing-dot spelling still matches.
production = [name for name in mapping
              if _key(mapping[name]) == _key(identity.REPOSITORY_ROOTS[name])
              or os.path.normcase(os.path.realpath(os.path.abspath(str(mapping[name]))))
              == _key(identity.REPOSITORY_ROOTS[name])]
if production:
    raise SystemExit('injected roots must not be production paths: '
                     + ', '.join(sorted(production)))
identity.REPOSITORY_ROOTS.clear()
identity.REPOSITORY_ROOTS.update(mapping)
sys.argv = [tool, *sys.argv[3:]]
runpy.run_path(tool, run_name='__main__')
'''


def profile_command(tool, nexus_root, auth_root, webhook_root, *arguments):
    """Arguments that run the profile tool with disposable repository roots injected."""
    supplied = list(map(str, arguments))
    if not any(argument == '--database' or argument.startswith('--database=')
               for argument in supplied):
        # The tool would otherwise fall back to the real live coordination directory.
        raise ValueError('an explicit --database is required')
    return ['-B', '-c', PROFILE_INJECTION, str(tool),
            repository_roots(nexus_root, auth_root, webhook_root), *supplied]


class GitFixture:
    """Disposable repository with one registered worktree per agent."""

    def __init__(self, root, agents=AGENTS):
        self.root = Path(root)
        self.root.mkdir(parents=True)
        self.git('init', '-q', '-b', 'main')
        (self.root / 'app').mkdir()
        (self.root / 'app/main.py').write_bytes(b'print("synthetic")\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'synthetic baseline')
        self.revision = self.git('rev-parse', 'HEAD').strip()
        for agent in agents:
            self.git('worktree', 'add', f'.worktrees/{agent}', '-b', f'agent/{agent}')

    def git(self, *args):
        completed = subprocess.run(
            [GIT, '-C', str(self.root), '-c', 'user.name=Synthetic Agent',
             '-c', 'user.email=synthetic@example.invalid', '-c', 'commit.gpgsign=false',
             '-c', 'core.autocrlf=false', *args],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False)
        if completed.returncode:
            raise AssertionError(f'git {args[0]} failed: {completed.stderr.strip()}')
        return completed.stdout

    def worktree(self, agent):
        return self.root / '.worktrees' / agent

    def status(self, agent):
        """Porcelain status of one registered worktree (the root itself holds the worktree dirs)."""
        completed = subprocess.run(
            [GIT, '-C', str(self.worktree(agent)), 'status', '--porcelain=v1', '--untracked-files=all'],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False)
        if completed.returncode:
            raise AssertionError(f'git status failed: {completed.stderr.strip()}')
        return completed.stdout