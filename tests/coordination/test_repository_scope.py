"""Repository-qualified worktree, reservation and review evidence tests.

Every checkout used here is a disposable Git repository created inside a
temporary directory. No configured repository, live database or production
service is read or written.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from mcp import ClientSession
from mcp.client.stdio import stdio_client

FIXTURE = Path(__file__).resolve().parent / 'repository_fixture.py'
PACKAGE = Path(__file__).resolve().parents[2] / 'coordination_hub'
IDENTITY = PACKAGE / 'identity.py'
SERVER = PACKAGE / 'server.py'
STORE = PACKAGE / 'store.py'
TOOL = PACKAGE / 'profile_tool.py'


def _fixture():
    import importlib.util
    spec = importlib.util.spec_from_file_location('coordination_repository_fixture', FIXTURE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load(module_name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepositoryScopeTests(unittest.TestCase):
    def setUp(self):
        self.identity = load('coordination_identity_repository', IDENTITY)
        if not Path(self.identity.GIT).exists():
            self.skipTest('Git is not available')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.fixture = _fixture().GitFixture(self.base / 'authfortress', agents=('security', 'codex'))
        patcher = patch.dict(self.identity.REPOSITORY_ROOTS, {'authfortress': self.fixture.root})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_configured_worktree_branch_and_clean_revision_pass(self):
        self.assertEqual(self.identity.worktree_for('authfortress', 'security'),
                         self.fixture.root / '.worktrees/security')
        self.identity.verify_submission('security', 'authfortress', self.fixture.revision)
        self.identity.verify_reservation_scope('security', 'authfortress')

    def test_missing_worktree_of_other_agent_does_not_block_owner(self):
        # development has no AuthFortress worktree; security still reserves normally.
        self.identity.verify_reservation_scope('security', 'authfortress')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_reservation_scope('development', 'authfortress')

    def test_unregistered_or_missing_worktree_fails_closed(self):
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('development', 'authfortress', self.fixture.revision)

    def test_wrong_revision_and_dirty_worktree_fail_closed(self):
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('security', 'authfortress', '0' * 40)
        dirty = self.fixture.root / '.worktrees/security/app/main.py'
        dirty.write_text('print("uncommitted")\n', encoding='utf-8')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('security', 'authfortress', self.fixture.revision)

    def test_wrong_branch_fails_closed(self):
        self.fixture.git('worktree', 'add', '.worktrees/development', '-b', 'feature/not-an-agent-branch')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('development', 'authfortress', self.fixture.revision)

    def test_stale_registered_worktree_of_another_agent_does_not_block(self):
        self.fixture.git('worktree', 'add', '.worktrees/development', '-b', 'agent/development')
        self.identity.verify_reservation_scope('security', 'authfortress')
        stale = self.fixture.root / '.worktrees/development'
        shutil.move(str(stale), str(self.base / 'development-moved'))
        self.assertFalse(stale.exists())
        # Git still lists the missing registration of the other agent; the caller
        # that is genuinely registered must not be affected by it.
        self.assertIn('development', self.fixture.git('worktree', 'list', '--porcelain'))
        self.identity.verify_reservation_scope('security', 'authfortress')
        self.identity.verify_submission('security', 'authfortress', self.fixture.revision)
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_reservation_scope('development', 'authfortress')

    def test_configured_root_symlink_is_rejected(self):
        alias = self.base / 'authfortress-alias'
        try:
            os.symlink(self.fixture.root, alias, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symbolic links are not available for this account')
        patcher = patch.dict(self.identity.REPOSITORY_ROOTS, {'authfortress': alias})
        patcher.start()
        self.addCleanup(patcher.stop)
        # The alias resolves to a perfectly registered repository, so only an
        # unresolved check of the configured root can reject it.
        self.assertEqual(alias.resolve(), self.fixture.root.resolve())
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_reservation_scope('security', 'authfortress')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('security', 'authfortress', self.fixture.revision)

    def test_main_checkout_and_foreign_paths_are_rejected(self):
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_worktree(self.fixture.root, 'security', self.fixture.root, 'authfortress')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_worktree(self.fixture.root, 'security', self.base / 'security', 'authfortress')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_worktree(self.base, 'security',
                                          self.fixture.root / '.worktrees/security', 'authfortress')

    def test_unlisted_repository_is_rejected(self):
        with self.assertRaises(self.identity.IdentityError):
            self.identity.worktree_for('unknown', 'security')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('security', 'unknown', self.fixture.revision)
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_revision(self.fixture.root, 'security',
                                          self.fixture.root / '.worktrees/security', 'unknown',
                                          self.fixture.revision)

    def test_reservation_preflight_tolerates_missing_dirs_but_rejects_links(self):
        self.identity.verify_no_links(self.fixture.root, '.worktrees/development/app/main.py')
        try:
            os.symlink(self.fixture.root / 'app', self.fixture.root / '.worktrees/security/linked')
        except (OSError, NotImplementedError):
            self.skipTest('Symbolic links are not available for this account')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_no_links(self.fixture.root, '.worktrees/security/linked/main.py')

    def test_configured_repositories_are_allowlisted_only(self):
        self.assertEqual(set(self.identity.REPOSITORY_ROOTS),
                         {'nexuscore', 'authfortress', 'webhook_manager'})
        store = load('coordination_store_repository_ids', STORE)
        self.assertTrue(set(self.identity.REPOSITORY_ROOTS) <= store.REPOSITORIES)
        # Namespaced in the store, deliberately unconfigured for identity checks.
        self.assertTrue({'agenthub', 'eventpipe', 'pipewatch'} <= store.REPOSITORIES)
        for unsupported in ('agenthub', 'eventpipe', 'pipewatch'):
            with self.assertRaises(self.identity.IdentityError):
                self.identity.worktree_for(unsupported, 'security')


class WebhookManagerScopeTests(unittest.TestCase):
    """Disposable WebHook_Manager repository; the real checkout is never read."""

    def setUp(self):
        self.identity = load('coordination_identity_webhook', IDENTITY)
        if not Path(self.identity.GIT).exists():
            self.skipTest('Git is not available')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.fixture = _fixture().GitFixture(self.base / 'webhook_manager',
                                            agents=('security', 'codex'))
        patcher = patch.dict(self.identity.REPOSITORY_ROOTS,
                             {'webhook_manager': self.fixture.root})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_configured_worktree_branch_and_clean_revision_pass(self):
        self.assertEqual(self.identity.worktree_for('webhook_manager', 'security'),
                         self.fixture.root / '.worktrees/security')
        self.identity.verify_reservation_scope('security', 'webhook_manager')
        self.identity.verify_submission('security', 'webhook_manager', self.fixture.revision)

    def test_missing_own_worktree_fails_closed(self):
        self.assertFalse((self.fixture.root / '.worktrees/development').exists())
        # Security is registered, so only development's own absence is reported.
        self.identity.verify_reservation_scope('security', 'webhook_manager')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_reservation_scope('development', 'webhook_manager')

    def test_wrong_branch_fails_closed(self):
        self.fixture.git('worktree', 'add', '.worktrees/development', '-b', 'feature/not-an-agent-branch')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_reservation_scope('development', 'webhook_manager')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_submission('development', 'webhook_manager', self.fixture.revision)

    def test_configured_root_must_be_the_webhook_manager_root(self):
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_worktree(self.base, 'security',
                                         self.fixture.root / '.worktrees/security',
                                         'webhook_manager')
        with self.assertRaises(self.identity.IdentityError):
            self.identity.verify_worktree(self.fixture.root, 'security',
                                         self.fixture.root / '.worktrees/security',
                                         'authfortress')


class WebhookManagerMcpTests(unittest.TestCase):
    """Actual MCP schema and namespaced reservations over real stdio.

    The real server runs in a child process; its roots, worktree and database are
    disposable. No real repository, worktree, database or profile is involved.
    """

    def setUp(self):
        self.fixture = _fixture()
        if not Path(self.fixture.GIT).exists():
            self.skipTest('Git is not available')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.database = str(self.base / 'hub.sqlite3')
        self.nexuscore = self.fixture.GitFixture(self.base / 'nexuscore')
        self.authfortress = self.fixture.GitFixture(self.base / 'authfortress',
                                                    agents=('security',))
        self.webhook_manager = self.fixture.GitFixture(self.base / 'webhook_manager',
                                                       agents=('security', 'codex'))

    def parameters(self, agent):
        return self.fixture.injected_parameters(
            SERVER, agent, self.database, self.nexuscore.worktree(agent),
            self.nexuscore.root, self.authfortress.root, self.webhook_manager.root)

    def test_actual_schema_and_webhook_manager_leases_are_namespaced(self):
        self.assertTrue(SERVER.exists(), 'MCP server must exist')
        asyncio.run(self._schema_and_namespaces())

    async def _schema_and_namespaces(self):
        async with stdio_client(self.parameters('codex')) as (r1, w1):  # noqa: SIM117
            async with stdio_client(self.parameters('security')) as (r2, w2):
                async with ClientSession(r1, w1) as reviewer, ClientSession(r2, w2) as worker:
                    await reviewer.initialize()
                    await worker.initialize()
                    tools = {tool.name: tool for tool in (await reviewer.list_tools()).tools}

                    leases = tools['lock_files'].inputSchema
                    owners = tools['get_file_owners'].inputSchema
                    for schema in (leases, owners):
                        parameter = schema['properties']['repository']
                        self.assertEqual(parameter.get('type'), 'string')
                        self.assertEqual(parameter.get('default'), 'nexuscore')
                    self.assertNotIn('repository', leases.get('required', []))
                    self.assertNotIn('repository', owners.get('required', []))
                    self.assertIn('repository',
                                  tools['submit_for_review'].inputSchema['required'])

                    created = await reviewer.call_tool('create_task', {
                        'request_id': str(uuid.uuid4()), 'title': 'WebHook manager scope',
                        'description': 'Synthetic task, disposable repositories'})
                    task_id = created.structuredContent['id']
                    claimed = await worker.call_tool('claim_task', {
                        'request_id': str(uuid.uuid4()), 'task_id': task_id})
                    self.assertFalse(claimed.isError, claimed.content)

                    lease = await worker.call_tool('lock_files', {
                        'request_id': str(uuid.uuid4()), 'task_id': task_id,
                        'repository': 'webhook_manager', 'paths': ['src/app.py'], 'ttl': 60})
                    self.assertFalse(lease.isError, lease.content)

                    for repository, present in (('webhook_manager', True),
                                                ('nexuscore', False),
                                                ('authfortress', False)):
                        listing = await reviewer.call_tool('get_file_owners', {
                            'paths': ['src/app.py'], 'repository': repository})
                        self.assertFalse(listing.isError, listing.content)
                        body = ''.join(getattr(block, 'text', '') for block in listing.content)
                        self.assertEqual('security' in body, present, (repository, body))

                    # Review evidence is verified against the WebHook_Manager worktree.
                    submitted = await worker.call_tool('submit_for_review', {
                        'request_id': str(uuid.uuid4()), 'task_id': task_id,
                        'report': 'Synthetic WebHook_Manager report',
                        'repository': 'webhook_manager',
                        'revision': self.webhook_manager.revision})
                    self.assertEqual(submitted.structuredContent['status'], 'in_review')
                    detail = await reviewer.call_tool('get_task', {'task_id': task_id})
                    self.assertEqual(detail.structuredContent['reports'][0]['repository'],
                                     'webhook_manager')
                    # Store namespaces without an allowlisted root stay rejected.
                    for unsupported in ('pipewatch', 'agenthub'):
                        rejected = await worker.call_tool('lock_files', {
                            'request_id': str(uuid.uuid4()), 'task_id': task_id,
                            'repository': unsupported, 'paths': ['src/app.py'], 'ttl': 60})
                        self.assertTrue(rejected.isError, unsupported)

    def test_missing_and_wrong_branch_worktrees_fail_closed_over_mcp(self):
        self.assertTrue(SERVER.exists(), 'MCP server must exist')
        asyncio.run(self._missing_and_wrong_branch())

    async def _missing_and_wrong_branch(self):
        self.assertFalse((self.webhook_manager.root / '.worktrees/development').exists())
        async with stdio_client(self.parameters('codex')) as (r1, w1):  # noqa: SIM117
            async with stdio_client(self.parameters('development')) as (r2, w2):
                async with ClientSession(r1, w1) as reviewer, ClientSession(r2, w2) as worker:
                    await reviewer.initialize()
                    await worker.initialize()
                    created = await reviewer.call_tool('create_task', {
                        'request_id': str(uuid.uuid4()), 'title': 'Missing worktree',
                        'description': 'Synthetic task, disposable repositories'})
                    task_id = created.structuredContent['id']
                    await worker.call_tool('claim_task', {
                        'request_id': str(uuid.uuid4()), 'task_id': task_id})

                    missing = await worker.call_tool('lock_files', {
                        'request_id': str(uuid.uuid4()), 'task_id': task_id,
                        'repository': 'webhook_manager', 'paths': ['src/app.py'], 'ttl': 60})
                    self.assertTrue(missing.isError)
                    self.assertIn('worktree', ''.join(
                        getattr(block, 'text', '') for block in missing.content).lower())

                    # A worktree on the wrong branch is not an assignment.
                    self.webhook_manager.git('worktree', 'add', '.worktrees/development',
                                             '-b', 'feature/not-an-agent-branch')
                    misbranched = await worker.call_tool('lock_files', {
                        'request_id': str(uuid.uuid4()), 'task_id': task_id,
                        'repository': 'webhook_manager', 'paths': ['src/other.py'], 'ttl': 60})
                    self.assertTrue(misbranched.isError)
                    self.assertIn('branch', ''.join(
                        getattr(block, 'text', '') for block in misbranched.content).lower())

                    # The same caller still reserves its own NexusCore worktree.
                    control = await worker.call_tool('lock_files', {
                        'request_id': str(uuid.uuid4()), 'task_id': task_id,
                        'paths': ['src/control.py'], 'ttl': 60})
                    self.assertFalse(control.isError, control.content)



class SharedFixtureIsolationTests(unittest.TestCase):
    """The shared fixture injection must never inherit a production repository root."""

    def setUp(self):
        self.fixtures = _fixture()
        self.identity = load('coordination_identity_isolation', IDENTITY)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def roots(self, **overrides):
        supplied = {name: str(self.base / name) for name in self.identity.REPOSITORY_ROOTS}
        supplied.update({name: str(value) for name, value in overrides.items()})
        return (supplied['nexuscore'], supplied['authfortress'], supplied['webhook_manager'])

    def test_mapping_holds_every_allowlisted_root_and_no_production_default(self):
        command = self.fixtures.injected_command(
            SERVER, 'codex', self.base / 'hub.sqlite3', self.base / 'worktree', *self.roots())
        mapping = json.loads(command[-2])
        self.assertEqual(set(mapping), set(self.identity.REPOSITORY_ROOTS))
        for name, value in mapping.items():
            self.assertEqual(Path(value), self.base / name)
            self.assertNotEqual(Path(value), self.identity.REPOSITORY_ROOTS[name])

    def test_an_omitted_root_is_rejected_before_the_server_reads_anything(self):
        for missing in ('', None, '   '):
            with self.subTest(root=missing), self.assertRaises(ValueError):
                self.fixtures.injected_command(
                    SERVER, 'codex', self.base / 'hub.sqlite3', self.base / 'worktree',
                    str(self.base / 'nexuscore'), str(self.base / 'authfortress'), missing)
        # The child process refuses an incomplete mapping instead of falling back to
        # the production root of the repository the caller left out.
        incomplete = json.dumps({'nexuscore': str(self.base / 'nexuscore'),
                                 'authfortress': str(self.base / 'authfortress')})
        completed = subprocess.run(
            [sys.executable, '-B', '-c', self.fixtures.INJECTION, str(SERVER), 'codex',
             str(self.base / 'hub.sqlite3'), str(self.base / 'worktree'), incomplete, ''],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn('injected roots must cover exactly', completed.stderr)
        self.assertIn('webhook_manager', completed.stderr)
        self.assertFalse((self.base / 'hub.sqlite3').exists())

    def test_child_rejects_a_blank_root_before_opening_the_database(self):
        # Direct JSON bypasses repository_roots, so this exercises the child guard
        # itself: Path('') silently means the current directory and the mapping
        # would still cover every allowlisted id.
        database = self.base / 'hub.sqlite3'
        for blank in ('', None, '   '):
            with self.subTest(root=blank):
                roots = json.dumps({'nexuscore': str(self.base / 'nexuscore'),
                                    'authfortress': str(self.base / 'authfortress'),
                                    'webhook_manager': blank})
                completed = subprocess.run(
                    [sys.executable, '-B', '-c', self.fixtures.INJECTION, str(SERVER),
                     'codex', str(database), str(self.base / 'worktree'), roots, ''],
                    stdin=subprocess.DEVNULL, capture_output=True, text=True,
                    timeout=60, check=False)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn('injected roots must be non-blank strings', completed.stderr)
                self.assertIn('webhook_manager', completed.stderr)
                self.assertFalse(database.exists())

    def test_profile_child_rejects_a_blank_root_before_running_the_tool(self):
        # The profile wrapper carries the same guard; Path('') must never reach the
        # tool, which would otherwise read the current directory as a repository.
        database = self.base / 'hub.sqlite3'
        roots = json.dumps({'nexuscore': str(self.base / 'nexuscore'),
                            'authfortress': str(self.base / 'authfortress'),
                            'webhook_manager': ''})
        completed = subprocess.run(
            [sys.executable, '-B', '-c', self.fixtures.PROFILE_INJECTION, str(TOOL),
             roots, '--agent', 'development', '--database', str(database)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, '')
        self.assertIn('injected roots must be non-blank strings', completed.stderr)
        self.assertIn('webhook_manager', completed.stderr)
        self.assertFalse(database.exists())


    def test_child_rejects_a_relative_root_before_the_server_reads_anything(self):
        # Path('webhook_manager') would resolve against the child's working
        # directory, so a relative root is never accepted as a fixture root.
        database = self.base / 'hub.sqlite3'
        roots = json.dumps({'nexuscore': 'nexuscore', 'authfortress': 'authfortress',
                            'webhook_manager': 'webhook_manager'})
        completed = subprocess.run(
            [sys.executable, '-B', '-c', self.fixtures.INJECTION, str(SERVER), 'codex',
             str(database), str(self.base / 'worktree'), roots, ''],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn('injected roots must be absolute paths', completed.stderr)
        self.assertIn('webhook_manager', completed.stderr)
        self.assertFalse(database.exists())

    def test_child_rejects_a_production_root_offered_explicitly(self):
        # Replacing the mapping closes accidental inheritance. A caller could still
        # name a real checkout on purpose, so the wrapper refuses the production
        # path of any repository before the server or the tool starts.
        database = self.base / 'hub.sqlite3'
        roots = json.dumps({
            'nexuscore': str(self.base / 'nexuscore'),
            'authfortress': str(self.base / 'authfortress'),
            'webhook_manager': str(self.identity.REPOSITORY_ROOTS['webhook_manager'])})
        for wrapper, target, arguments in (
                (self.fixtures.INJECTION, str(SERVER),
                 ['codex', str(database), str(self.base / 'worktree'), roots, '']),
                (self.fixtures.PROFILE_INJECTION, str(TOOL),
                 [roots, '--agent', 'development', '--database', str(database)])):
            with self.subTest(wrapper=target):
                completed = subprocess.run(
                    [sys.executable, '-B', '-c', wrapper, target, *arguments],
                    stdin=subprocess.DEVNULL, capture_output=True, text=True,
                    timeout=60, check=False)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn('injected roots must not be production paths', completed.stderr)
                self.assertIn('webhook_manager', completed.stderr)
                self.assertFalse(database.exists())

    def test_profile_wrapper_requires_an_explicit_database(self):
        # The profile tool otherwise defaults to the real live coordination directory.
        with self.assertRaises(ValueError):
            self.fixtures.profile_command(TOOL, *self.roots(), '--agent', 'development')


class ReviewEvidenceTests(unittest.TestCase):
    def test_submission_evidence_records_the_submitted_repository(self):
        store = load('coordination_store_repository_evidence', STORE)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            task = hub.create_task('codex', 'AuthFortress work', 'Synthetic')['id']
            hub.claim_task('security', task)
            revision = 'f' * 40
            submitted = hub.submit_for_review('security', task, 'Synthetic report',
                                              'authfortress', revision)
            evidence = hub.get_task(task)['reports'][0]
            self.assertEqual((evidence['repository'], evidence['revision']), ('authfortress', revision))
            self.assertEqual(hub.review_task('codex', task, True, 'Reviewed',
                                             submitted['version'])['status'], 'completed')
            self.assertEqual(hub.list_tasks()[0]['owner'], 'security')


if __name__ == '__main__':
    unittest.main()
