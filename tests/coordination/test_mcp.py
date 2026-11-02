import asyncio
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import stdio_client

FIXTURE = Path(__file__).resolve().parent / 'repository_fixture.py'
SERVER = Path(__file__).resolve().parents[2] / 'coordination_hub' / 'server.py'


def fixtures():
    import importlib.util
    spec = importlib.util.spec_from_file_location('coordination_repository_fixture', FIXTURE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MCPContractTests(unittest.TestCase):
    def setUp(self):
        module = fixtures()
        self.injected = module.injected_parameters
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.nexuscore = module.GitFixture(self.base / 'nexuscore')
        self.authfortress = module.GitFixture(self.base / 'authfortress')

    def parameters(self, agent, database, live_root='', worktree=None):
        """stdio server with disposable repository roots injected via runpy."""
        return self.injected(SERVER, agent, database, worktree or self.nexuscore.worktree(agent),
                             self.nexuscore.root, self.authfortress.root, live_root)

    def run_startup(self, agent, database, live_root='', worktree=None, timeout=60):
        """Run the injected server once with a closed stdin and return the process result."""
        parameters = self.parameters(agent, database, live_root, worktree)
        return subprocess.run([parameters.command, *parameters.args], stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=timeout, check=False)

    def test_provisioned_live_database_starts(self):
        from coordination_hub.persistent import provision
        with tempfile.TemporaryDirectory() as directory:
            live = Path(directory) / 'NexusCoreCoordination'
            database = provision(live)
            result = self.run_startup('codex', database, live_root=live)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

    def test_live_database_missing_does_not_get_created(self):
        from coordination_hub.persistent import provision
        with tempfile.TemporaryDirectory() as directory:
            live = Path(directory) / 'NexusCoreCoordination'
            database = provision(live)
            database.unlink()
            result = self.run_startup('codex', database, live_root=live)
            self.assertNotEqual(result.returncode, 0)
            # The failure must come from the missing live database, not from the
            # injected repository roots or the argument layout.
            self.assertIn(b'Hub database is missing', result.stderr)
            self.assertFalse(database.exists())

    def test_rejects_wrong_worktree_before_database_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            rejected = Path(directory) / 'rejected' / 'hub.sqlite3'
            rejected.parent.mkdir()
            wrong = self.run_startup('development', rejected,
                                     worktree=self.nexuscore.worktree('security'))
            # The identity check exits with status 2 before the database is opened.
            self.assertEqual(wrong.returncode, 2, wrong.stderr.decode(errors='replace'))
            self.assertFalse(rejected.exists())
            # Positive control through the same injection: the assigned worktree starts.
            accepted = Path(directory) / 'accepted' / 'hub.sqlite3'
            accepted.parent.mkdir()
            correct = self.run_startup('development', accepted)
            self.assertEqual(correct.returncode, 0, correct.stderr.decode(errors='replace'))
            self.assertTrue(accepted.exists())

    def test_stdio_task_flow(self):
        self.assertTrue(SERVER.exists(), 'MCP server must exist')
        asyncio.run(self._flow())

    def test_tools_expose_repository_qualified_leases(self):
        self.assertTrue(SERVER.exists(), 'MCP server must exist')
        asyncio.run(self._repository_contract())

    def test_legacy_request_id_replays_to_stored_result(self):
        """A request ID persisted before the repository argument existed must still replay.

        The previous Hub hashed {"task_id","paths","ttl"} for a default NexusCore
        reservation. The candidate must reproduce that canonical payload exactly.
        """
        from coordination_hub.store import Store
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'hub.sqlite3'
            store = Store(database)
            task_id = store.create_task('codex', 'Legacy retry', 'Synthetic')['id']
            store.claim_task('development', task_id)
            paths = ['docs/legacy-retry.md']
            stored = store.lock_files('development', task_id, paths, 600)
            legacy = {'operation': 'lock_files', 'payload': {'task_id': task_id, 'paths': paths, 'ttl': 600}}
            canonical = json.dumps(legacy, sort_keys=True, ensure_ascii=False,
                                   separators=(',', ':'), allow_nan=False)
            request_id = str(uuid.uuid4())
            with closing(sqlite3.connect(database)) as db, db:
                db.execute('INSERT INTO requests VALUES (?,?,?,?)',
                           ('development', request_id, hashlib.sha256(canonical.encode('utf-8')).hexdigest(),
                            json.dumps(stored)))
            replay = asyncio.run(self._replay_legacy(database, task_id, paths, request_id))
            self.assertFalse(replay.isError, replay.content)
            self.assertEqual(replay.structuredContent['lease_ids'], stored['lease_ids'])
            self.assertEqual(replay.structuredContent['expires_at'], stored['expires_at'])

    async def _replay_legacy(self, database, task_id, paths, request_id):
        async with stdio_client(self.parameters('development', database)) as (read, write), \
                ClientSession(read, write) as worker:
            await worker.initialize()
            return await worker.call_tool('lock_files', {
                'request_id': request_id, 'task_id': task_id, 'paths': paths, 'ttl': 600})

    async def _repository_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / 'hub.sqlite3')
            async with stdio_client(self.parameters('codex', database)) as (r1, w1):  # noqa: SIM117
                async with stdio_client(self.parameters('development', database)) as (r2, w2):
                    async with ClientSession(r1, w1) as reviewer, ClientSession(r2, w2) as worker:
                        await reviewer.initialize()
                        await worker.initialize()
                        tool_info = (await reviewer.list_tools()).tools
                        lock_tool = next(tool for tool in tool_info if tool.name == 'lock_files')
                        self.assertIn('repository', lock_tool.inputSchema['properties'])
                        self.assertEqual(lock_tool.inputSchema['properties']['repository'].get('default'),
                                         'nexuscore')
                        owners_tool = next(tool for tool in tool_info if tool.name == 'get_file_owners')
                        self.assertIn('repository', owners_tool.inputSchema['properties'])
                        created = await reviewer.call_tool('create_task', {
                            'request_id': str(uuid.uuid4()), 'title': 'Repository scope',
                            'description': 'Synthetic task for lease namespaces'})
                        self.assertFalse(created.isError)
                        task_id = created.structuredContent['id']
                        claimed = await worker.call_tool('claim_task', {'request_id': str(uuid.uuid4()),
                                                                        'task_id': task_id})
                        self.assertFalse(claimed.isError)
                        lease = await worker.call_tool('lock_files', {
                            'request_id': str(uuid.uuid4()), 'task_id': task_id,
                            'paths': ['app/main.py'], 'ttl': 60})
                        self.assertFalse(lease.isError, lease.content)
                        same_path_other_repository = await reviewer.call_tool('get_file_owners', {
                            'paths': ['app/main.py'], 'repository': 'authfortress'})
                        self.assertFalse(same_path_other_repository.isError)
                        self.assertNotIn('development', ''.join(
                            getattr(block, 'text', '') for block in same_path_other_repository.content))
                        unlisted = await worker.call_tool('lock_files', {
                            'request_id': str(uuid.uuid4()), 'task_id': task_id,
                            'paths': ['app/main.py'], 'repository': 'unknown', 'ttl': 60})
                        self.assertTrue(unlisted.isError)

    async def _flow(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / 'hub.sqlite3')
            auth_head = self.authfortress.revision
            async with stdio_client(self.parameters('codex', database)) as (r1, w1):  # noqa: SIM117
                async with stdio_client(self.parameters('development', database)) as (r2, w2):
                    async with stdio_client(self.parameters('security', database)) as (r3, w3):
                        async with ClientSession(r1, w1) as reviewer, ClientSession(r2, w2) as worker, \
                                ClientSession(r3, w3) as authworker:
                            initialization = await reviewer.initialize()
                            self.assertIn('reserve', initialization.instructions.lower())
                            await worker.initialize()
                            await authworker.initialize()
                            tool_info = (await reviewer.list_tools()).tools
                            tools = {tool.name for tool in tool_info}
                            inbox_tool = next(tool for tool in tool_info if tool.name == 'check_inbox')
                            self.assertTrue(inbox_tool.annotations.readOnlyHint)
                            lock_tool = next(tool for tool in tool_info if tool.name == 'lock_files')
                            self.assertIn('repository', lock_tool.inputSchema['properties'])
                            self.assertEqual(lock_tool.inputSchema['properties']['repository'].get('default'),
                                             'nexuscore')
                            self.assertTrue({'create_task','claim_task','submit_for_review','review_task',
                                             'heartbeat','get_agent_status','renew_leases'} <= tools)
                            request_id = str(uuid.uuid4())
                            payload = {'request_id': request_id, 'title':'Synthetic task','description':'No production access'}
                            created = await reviewer.call_tool('create_task', payload)
                            self.assertFalse(created.isError)
                            repeated = await reviewer.call_tool('create_task', payload)
                            self.assertEqual(created.structuredContent, repeated.structuredContent)
                            task_id = created.structuredContent['id']
                            claimed = await worker.call_tool('claim_task', {'request_id': str(uuid.uuid4()), 'task_id':task_id})
                            self.assertEqual(claimed.structuredContent['owner'], 'development')
                            pulse = await worker.call_tool('heartbeat', {'request_id': str(uuid.uuid4()), 'status': 'working'})
                            self.assertEqual(pulse.structuredContent['agent'], 'development')
                            status = await reviewer.call_tool('get_agent_status', {'agent': 'development'})
                            self.assertEqual(status.structuredContent['status'], 'working')
                            lease = await worker.call_tool('lock_files', {
                                'request_id': str(uuid.uuid4()), 'task_id': task_id,
                                'paths': ['docs/__coordination_synthetic_probe__.md'], 'ttl': 60})
                            self.assertFalse(lease.isError)
                            renewed = await worker.call_tool('renew_leases', {
                                'request_id': str(uuid.uuid4()), 'task_id': task_id,
                                'lease_ids': lease.structuredContent['lease_ids'], 'ttl': 120})
                            self.assertFalse(renewed.isError)
                            # Full submit and review flow in the second repository namespace.
                            auth_task = await reviewer.call_tool('create_task', {
                                'request_id': str(uuid.uuid4()), 'title': 'AuthFortress evidence',
                                'description': 'Synthetic repository-qualified task'})
                            auth_task_id = auth_task.structuredContent['id']
                            auth_claimed = await authworker.call_tool('claim_task', {
                                'request_id': str(uuid.uuid4()), 'task_id': auth_task_id})
                            self.assertEqual(auth_claimed.structuredContent['owner'], 'security')
                            auth_lease = await authworker.call_tool('lock_files', {
                                'request_id': str(uuid.uuid4()), 'task_id': auth_task_id,
                                'repository': 'authfortress', 'paths': ['app/main.py'], 'ttl': 60})
                            self.assertFalse(auth_lease.isError, auth_lease.content)
                            auth_owners = await reviewer.call_tool('get_file_owners', {
                                'paths': ['app/main.py'], 'repository': 'authfortress'})
                            self.assertIn('security', ''.join(getattr(block, 'text', '')
                                                              for block in auth_owners.content))
                            nexuscore_owners = await reviewer.call_tool('get_file_owners', {
                                'paths': ['app/main.py'], 'repository': 'nexuscore'})
                            self.assertNotIn('security', ''.join(getattr(block, 'text', '')
                                                                 for block in nexuscore_owners.content))
                            submitted = await authworker.call_tool('submit_for_review', {
                                'request_id': str(uuid.uuid4()), 'task_id': auth_task_id,
                                'report': 'Synthetic AuthFortress report', 'repository': 'authfortress',
                                'revision': auth_head})
                            self.assertEqual(submitted.structuredContent['status'], 'in_review')
                            detail = await reviewer.call_tool('get_task', {'task_id': auth_task_id})
                            self.assertEqual(detail.structuredContent['reports'][0]['body'],
                                             'Synthetic AuthFortress report')
                            self.assertEqual(detail.structuredContent['reports'][0]['repository'], 'authfortress')
                            result = await reviewer.call_tool('review_task', {
                                'request_id': str(uuid.uuid4()), 'task_id': auth_task_id, 'approved': True,
                                'report': 'Checked', 'expected_version': submitted.structuredContent['version']})
                            self.assertEqual(result.structuredContent['status'], 'completed')
                            unlisted = await reviewer.call_tool('get_file_owners', {
                                'paths': ['app/main.py'], 'repository': 'unknown'})
                            self.assertTrue(unlisted.isError)


if __name__ == '__main__':
    unittest.main()
