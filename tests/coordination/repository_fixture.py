"""Disposable Git repositories and a runpy injection wrapper for the Hub tests.

Every repository used through this module exists only inside a temporary
directory. The injection wrapper runs the real server with a patched
``identity.REPOSITORY_ROOTS`` mapping, so the full tool flow can be exercised
without depending on any real agent worktree being present or clean. The
production allowlist in ``identity.py`` stays fixed; nothing here is
environment-configurable.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

GIT = 'C:/Program Files/Git/cmd/git.exe'
AGENTS = ('security', 'development', 'codex')

# sys.argv layout for `python -c INJECTION <server> <agent> <database> <worktree> <nexus_root> <auth_root>`.
INJECTION = '''import runpy, sys
from pathlib import Path
server, agent, database, worktree, nexus_root, auth_root = sys.argv[1:7]
sys.path.insert(0, str(Path(server).parent))
import identity
identity.REPOSITORY_ROOTS['nexuscore'] = Path(nexus_root)
identity.REPOSITORY_ROOTS['authfortress'] = Path(auth_root)
sys.argv = [server, agent, database, worktree]
runpy.run_path(server, run_name='__main__')
'''


def load(module_name, path):
    """Load a module by path, so tests never depend on the current package layout."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def injected_command(server, agent, database, worktree, nexus_root, auth_root):
    """Arguments for the stdio server with disposable repository roots injected."""
    return ['-B', '-c', INJECTION, str(server), agent, str(database), str(worktree),
            str(nexus_root), str(auth_root)]


def injected_parameters(server, agent, database, worktree, nexus_root, auth_root):
    from mcp import StdioServerParameters
    return StdioServerParameters(
        command=sys.executable,
        args=injected_command(server, agent, database, worktree, nexus_root, auth_root))


class GitFixture:
    """Disposable repository with one registered worktree per agent."""

    def __init__(self, root, agents=AGENTS):
        self.root = Path(root)
        self.root.mkdir(parents=True)
        self.git('init', '-q', '-b', 'main')
        (self.root / 'app').mkdir()
        (self.root / 'app/main.py').write_text('print("synthetic")\n', encoding='utf-8')
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
