"""Tests for the read-only OpenCode Hub configuration emitter.

Every database and every Git repository used here is created inside a temporary
directory. The repository roots are injected into both the tool and the server
with test-only runpy wrappers, so the emitted configuration is consumed through
the real stdio server without reading a real agent worktree or the production
allowlist.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from mcp import ClientSession
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'coordination_hub'
TOOL = PACKAGE / 'profile_tool.py'
STORE = PACKAGE / 'store.py'
FIXTURE = Path(__file__).resolve().parent / 'repository_fixture.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProfileToolTests(unittest.TestCase):
    def setUp(self):
        from coordination_hub.store import Store
        self.fixtures = load('coordination_profile_fixture', FIXTURE)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.database = self.base / 'hub.sqlite3'
        Store(self.database)
        self.nexuscore = self.fixtures.GitFixture(self.base / 'repos' / 'nexuscore')
        self.authfortress = self.fixtures.GitFixture(self.base / 'repos' / 'authfortress',
                                                     agents=('security',))
        # The emitted server is pinned to the selected agent worktree, so each
        # disposable worktree needs its own copy of the Hub package.
        self.install_server(self.nexuscore, 'security', 'development')
        roots = patch.dict('coordination_hub.identity.REPOSITORY_ROOTS', {
            'nexuscore': self.nexuscore.root,
            'authfortress': self.authfortress.root,
        })
        roots.start()
        self.addCleanup(roots.stop)
        self.tool = load('coordination_profile_tool', TOOL)
        self.store_module = load('coordination_profile_store', STORE)

    def install_server(self, repository, *agents):
        """Give disposable worktrees the package the emitted profile runs."""
        for agent in agents:
            shutil.copytree(PACKAGE, repository.worktree(agent) / 'coordination_hub',
                            ignore=shutil.ignore_patterns('__pycache__', 'profiles'))

    def cli(self, *arguments):
        command = self.fixtures.profile_command(TOOL, self.nexuscore.root,
                                               self.authfortress.root, *arguments)
        return subprocess.run([sys.executable, *command],
                              capture_output=True, text=True, timeout=60, check=False)

    def test_emits_the_existing_opencode_schema_for_both_roles(self):
        emitted_servers = set()
        for agent in ('security', 'development'):
            with self.subTest(agent=agent):
                server = self.tool.build_config(agent, self.database)['mcp']['servers']['nexus_hub']
                self.assertEqual(server['type'], 'local')
                self.assertFalse(server['disabled'])
                command = server['command']
                self.assertEqual(len(command), 5)
                self.assertEqual(command[0], sys.executable)
                expected_server = self.nexuscore.worktree(agent) / 'coordination_hub' / 'server.py'
                self.assertEqual(command[1], str(expected_server))
                self.assertTrue(expected_server.is_file())
                self.assertEqual(command[2], agent)
                self.assertEqual(command[3], str(self.database))
                self.assertEqual(command[4], str(self.nexuscore.worktree(agent)))
                emitted_servers.add(command[1])
        self.assertEqual(len(emitted_servers), 2)

    def test_emitted_server_is_pinned_to_the_role_worktree(self):
        """A profile must not run the Hub code of the emitter's checkout."""
        emitter = Path(self.tool.__file__).resolve().parent
        for agent in ('security', 'development'):
            with self.subTest(agent=agent):
                command = self.tool.build_config(agent, self.database)[
                    'mcp']['servers']['nexus_hub']['command']
                emitted = Path(command[1]).resolve()
                self.assertEqual(emitted.parent.parent, self.nexuscore.worktree(agent).resolve())
                self.assertNotEqual(emitted.parent, emitter)
                self.assertNotEqual(emitted, (emitter / 'server.py').resolve())

    def test_cli_prints_only_the_profile_on_stdout(self):
        result = self.cli('--agent', 'development', '--database', self.database)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, '')
        self.assertEqual(json.loads(result.stdout), self.tool.build_config('development', self.database))

    def test_generated_profile_serves_stdio_with_a_temporary_database(self):
        import asyncio
        for agent in ('security', 'development'):
            with self.subTest(agent=agent):
                emitted = self.cli('--agent', agent, '--database', self.database)
                self.assertEqual(emitted.returncode, 0, emitted.stderr)
                server = json.loads(emitted.stdout)['mcp']['servers']['nexus_hub']
                asyncio.run(self._consume(server['command']))

    async def _consume(self, command):
        parameters = self.fixtures.injected_parameters(
            command[1], command[2], command[3], command[4],
            self.nexuscore.root, self.authfortress.root)
        async with stdio_client(parameters) as (read, write), \
                ClientSession(read, write) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            self.assertIn('lock_files', names)
            self.assertIn('submit_for_review', names)
            tasks = await session.call_tool('list_tasks', {})
            self.assertFalse(tasks.isError)
            payload = (tasks.structuredContent if tasks.structuredContent is not None
                       else json.loads(tasks.content[0].text))
            if isinstance(payload, dict):
                payload = payload.get('result', payload)
            self.assertEqual(payload, [])

    def test_rejects_roles_outside_the_opencode_pair(self):
        with self.assertRaises(self.tool.ProfileError) as caught:
            self.tool.build_config('codex', self.database)
        self.assertEqual(str(caught.exception), 'invalid arguments')
        result = self.cli('--agent', 'codex', '--database', self.database)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, 'error: invalid arguments\n')

    def test_rejects_unsupported_missing_and_linked_paths(self):
        with self.assertRaises(self.tool.ProfileError) as caught:
            self.tool.build_config('development', self.base / 'other.sqlite3')
        self.assertEqual(str(caught.exception), 'unsupported database path')
        missing = self.base / 'absent' / 'hub.sqlite3'
        with self.assertRaises(self.tool.ProfileError) as caught:
            self.tool.build_config('development', missing)
        self.assertEqual(str(caught.exception), 'database not found')
        self.assertFalse(missing.exists())
        try:
            (self.base / 'linked').mkdir()
            os.symlink(self.database, self.base / 'linked' / 'hub.sqlite3')
        except (OSError, NotImplementedError):
            self.skipTest('Symbolic links are not available for this account')
        with self.assertRaises(self.tool.ProfileError) as caught:
            self.tool.build_config('development', self.base / 'linked' / 'hub.sqlite3')
        self.assertEqual(str(caught.exception), 'database path is linked')

    def test_rejects_a_database_with_the_wrong_schema(self):
        unrelated = self.base / 'unrelated' / 'hub.sqlite3'
        unrelated.parent.mkdir()
        with closing(sqlite3.connect(unrelated)) as db, db:
            db.execute('CREATE TABLE unrelated (value TEXT)')
        with self.assertRaises(self.tool.ProfileError) as caught:
            self.tool.build_config('development', unrelated)
        self.assertEqual(str(caught.exception), 'database schema mismatch')
        empty = self.base / 'empty' / 'hub.sqlite3'
        empty.parent.mkdir()
        empty.touch()
        with self.assertRaises(self.tool.ProfileError) as caught:
            self.tool.build_config('development', empty)
        self.assertEqual(str(caught.exception), 'database schema mismatch')

    def test_rejects_matching_metadata_with_unrelated_schema(self):
        """Matching application id and version do not prove the server schema."""
        forged = self.base / 'forged' / 'hub.sqlite3'
        forged.parent.mkdir()
        with closing(sqlite3.connect(forged)) as db, db:
            db.execute('CREATE TABLE unrelated (value TEXT)')
            db.execute('PRAGMA application_id = 1314419522')
            db.execute('PRAGMA user_version = 4')
        with closing(sqlite3.connect(forged)) as db:
            self.assertEqual(db.execute('PRAGMA application_id').fetchone()[0], 1314419522)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
        # The real server refuses exactly this database through the same validator.
        with self.assertRaises(self.store_module.Conflict):
            self.store_module.Store(forged, existing_only=True)
        with self.assertRaises(self.tool.ProfileError) as caught:
            self.tool.build_config('development', forged)
        self.assertEqual(str(caught.exception), 'database schema mismatch')

    def test_rejects_a_missing_runtime_path(self):
        """The server must exist in the worktree the emitted profile will run."""
        bare = self.fixtures.GitFixture(self.base / 'repos' / 'bare', agents=('development',))
        with patch.dict('coordination_hub.identity.REPOSITORY_ROOTS', {'nexuscore': bare.root}), \
                self.assertRaises(self.tool.ProfileError) as caught:
            self.tool.build_config('development', self.database)
        self.assertEqual(str(caught.exception), 'runtime unavailable')

    def test_rejects_a_nonregular_target_server(self):
        """A directory or other non-regular target entry is not a server."""
        bare = self.fixtures.GitFixture(self.base / 'repos' / 'nonregular',
                                        agents=('development',))
        package = bare.worktree('development') / 'coordination_hub'
        package.mkdir()
        (package / 'server.py').mkdir()
        with patch.dict('coordination_hub.identity.REPOSITORY_ROOTS', {'nexuscore': bare.root}), \
                self.assertRaises(self.tool.ProfileError) as caught:
            self.tool.build_config('development', self.database)
        self.assertEqual(str(caught.exception), 'runtime unavailable')

    def test_rejects_a_linked_target_server(self):
        """A link or reparse point at the target server fails closed."""
        bare = self.fixtures.GitFixture(self.base / 'repos' / 'linked-server',
                                        agents=('development',))
        package = bare.worktree('development') / 'coordination_hub'
        package.mkdir()
        try:
            os.symlink(PACKAGE / 'server.py', package / 'server.py')
        except (OSError, NotImplementedError):
            self.skipTest('Symbolic links are not available for this account')
        with patch.dict('coordination_hub.identity.REPOSITORY_ROOTS', {'nexuscore': bare.root}), \
                self.assertRaises(self.tool.ProfileError) as caught:
            self.tool.build_config('development', self.database)
        self.assertEqual(str(caught.exception), 'runtime unavailable')

    def test_rejects_an_unregistered_worktree_without_blocking_a_registered_one(self):
        """A missing agent worktree fails through the real identity check."""
        partial = self.fixtures.GitFixture(self.base / 'repos' / 'partial', agents=('security',))
        self.install_server(partial, 'security')
        with patch.dict('coordination_hub.identity.REPOSITORY_ROOTS', {'nexuscore': partial.root}):
            self.tool.build_config('security', self.database)
            with self.assertRaises(self.tool.ProfileError) as caught:
                self.tool.build_config('development', self.database)
        self.assertEqual(str(caught.exception), 'agent worktree unavailable')

    def test_rejects_a_worktree_registered_on_the_wrong_branch(self):
        """The branch check still runs against a real registration, not a stub."""
        wrong = self.fixtures.GitFixture(self.base / 'repos' / 'wrong-branch', agents=('security',))
        wrong.git('worktree', 'add', '.worktrees/development', '-b', 'feature/not-an-agent-branch')
        self.install_server(wrong, 'security')
        with patch.dict('coordination_hub.identity.REPOSITORY_ROOTS', {'nexuscore': wrong.root}):
            self.tool.build_config('security', self.database)
            with self.assertRaises(self.tool.ProfileError) as caught:
                self.tool.build_config('development', self.database)
        self.assertEqual(str(caught.exception), 'agent worktree unavailable')

    def test_invalid_cli_never_echoes_the_input(self):
        result = self.cli('--agent', 'development', '--database', self.database,
                          '--output', 'secret-candidate-path.json')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, 'error: invalid arguments\n')
        self.assertNotIn('secret-candidate-path', result.stderr)
        self.assertNotIn('output', result.stderr)
        self.assertEqual(self.cli('--database', self.database).returncode, 2)

    def test_emitting_and_failing_never_write_to_the_database(self):
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        listing = sorted(path.name for path in self.base.iterdir())
        self.assertEqual(self.cli('--agent', 'security', '--database', self.database).returncode, 0)
        self.assertEqual(self.cli('--agent', 'development', '--database', self.base / 'absent' /
                                  'hub.sqlite3').returncode, 2)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), before)
        self.assertEqual(sorted(path.name for path in self.base.iterdir()), listing)
        self.assertFalse((self.base / 'hub.sqlite3-wal').exists())
        self.assertFalse((self.base / 'hub.sqlite3-shm').exists())


if __name__ == '__main__':
    unittest.main()
