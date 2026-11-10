"""Repository-qualified worktree, reservation and review evidence tests.

Every checkout used here is a disposable Git repository created inside a
temporary directory. No configured repository, live database or production
service is read or written.
"""
import asyncio
import os
import shutil
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

# Runs the real server in a child process with disposable repository roots. The
# production allowlist in identity.py stays fixed; only this process's mapping is
# replaced, exactly like the shared test fixture injection.
SERVER_INJECTION = '''import runpy, sys
from pathlib import Path
server, agent, database, worktree, nexuscore, authfortress, webhook_manager = sys.argv[1:8]
sys.path.insert(0, str(Path(server).parent))
import identity
identity.REPOSITORY_ROOTS['nexuscore'] = Path(nexuscore)
identity.REPOSITORY_ROOTS['authfortress'] = Path(authfortress)
identity.REPOSITORY_ROOTS['webhook_manager'] = Path(webhook_manager)
sys.argv = [server, agent, database, worktree]
runpy.run_path(server, run_name='__main__')
'''


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
        from mcp import StdioServerParameters
        roots = [str(self.nexuscore.root), str(self.authfortress.root),
                 str(self.webhook_manager.root)]
        return StdioServerParameters(
            command=sys.executable,
            args=['-B', '-c', SERVER_INJECTION, str(SERVER), agent, self.database,
                  str(self.nexuscore.worktree(agent)), *roots])

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
