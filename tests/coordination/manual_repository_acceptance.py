"""Manual acceptance harness for repository-qualified reservations and review.

Not collected by ``unittest discover`` (the file name does not start with
``test_``). It runs the real MCP server against disposable Git repositories with
an injected root mapping and a database inside a temporary directory, so no
live Hub data, real agent worktree, profile or running client is touched.

Usage (from the repository root):

    python -B tests/coordination/manual_repository_acceptance.py
"""
import asyncio
import importlib.util
import tempfile
import uuid
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import stdio_client

HERE = Path(__file__).resolve().parent
SERVER = HERE.parents[1] / 'coordination_hub' / 'server.py'
FIXTURE = HERE / 'repository_fixture.py'

results = []


def check(name, condition, detail=''):
    results.append((name, bool(condition), detail))
    print(f'{"PASS" if condition else "FAIL"}  {name}{"  " + detail if detail else ""}')


def text_of(result):
    return ''.join(getattr(block, 'text', '') for block in result.content)


async def run():
    spec = importlib.util.spec_from_file_location('coordination_repository_fixture', FIXTURE)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)

    base = Path(tempfile.mkdtemp(prefix='nexuscore-hub-acceptance-'))
    database = str(base / 'hub.sqlite3')
    nexuscore = fixtures.GitFixture(base / 'nexuscore')
    # Only security has an AuthFortress worktree, which mirrors the real registration.
    authfortress = fixtures.GitFixture(base / 'authfortress', agents=('security',))

    def parameters(agent):
        return fixtures.injected_parameters(SERVER, agent, database, nexuscore.worktree(agent),
                                            nexuscore.root, authfortress.root)

    async with stdio_client(parameters('codex')) as (r1, w1):  # noqa: SIM117
        async with stdio_client(parameters('security')) as (r2, w2):
            async with stdio_client(parameters('development')) as (r3, w3):
                async with ClientSession(r1, w1) as reviewer, ClientSession(r2, w2) as worker, \
                        ClientSession(r3, w3) as other:
                    await reviewer.initialize()
                    await worker.initialize()
                    await other.initialize()

                    task = await reviewer.call_tool('create_task', {
                        'request_id': str(uuid.uuid4()), 'title': 'AuthFortress acceptance',
                        'description': 'Synthetic task, temporary database'})
                    task_id = task.structuredContent['id']
                    claimed = await worker.call_tool('claim_task', {'request_id': str(uuid.uuid4()),
                                                                    'task_id': task_id})
                    check('security claims its own task', not claimed.isError)

                    check('disposable AuthFortress worktree is clean at its baseline',
                          not authfortress.status('security').strip(),
                          authfortress.revision[:12])

                    lease = await worker.call_tool('lock_files', {
                        'request_id': str(uuid.uuid4()), 'task_id': task_id,
                        'repository': 'authfortress', 'paths': ['app/main.py'], 'ttl': 300})
                    check('security reserves app/main.py in authfortress', not lease.isError,
                          text_of(lease)[:120])

                    owners = await reviewer.call_tool('get_file_owners', {
                        'paths': ['app/main.py'], 'repository': 'authfortress'})
                    check('authfortress owners are visible', 'security' in text_of(owners))
                    nexuscore_owners = await reviewer.call_tool('get_file_owners', {
                        'paths': ['app/main.py'], 'repository': 'nexuscore'})
                    check('nexuscore namespace is unaffected', 'security' not in text_of(nexuscore_owners))

                    own_task = await reviewer.call_tool('create_task', {
                        'request_id': str(uuid.uuid4()), 'title': 'Development reservation attempt',
                        'description': 'Synthetic task, temporary database'})
                    await other.call_tool('claim_task', {'request_id': str(uuid.uuid4()),
                                                         'task_id': own_task.structuredContent['id']})
                    blocked = await other.call_tool('lock_files', {
                        'request_id': str(uuid.uuid4()), 'task_id': own_task.structuredContent['id'],
                        'repository': 'authfortress', 'paths': ['app/other.py'], 'ttl': 300})
                    check('development cannot reserve another repository worktree', blocked.isError,
                          text_of(blocked)[:160])

                    submitted = await worker.call_tool('submit_for_review', {
                        'request_id': str(uuid.uuid4()), 'task_id': task_id,
                        'report': 'Synthetic AuthFortress evidence', 'repository': 'authfortress',
                        'revision': authfortress.revision})
                    check('security submits AuthFortress evidence', not submitted.isError,
                          text_of(submitted)[:160])
                    if not submitted.isError:
                        detail = await reviewer.call_tool('get_task', {'task_id': task_id})
                        evidence = detail.structuredContent['reports'][0]
                        check('evidence records the submitted repository and revision',
                              (evidence['repository'], evidence['revision'])
                              == ('authfortress', authfortress.revision))
                        approved = await reviewer.call_tool('review_task', {
                            'request_id': str(uuid.uuid4()), 'task_id': task_id, 'approved': True,
                            'report': 'Synthetic review',
                            'expected_version': submitted.structuredContent['version']})
                        check('codex reviews the AuthFortress submission',
                              approved.structuredContent['status'] == 'completed')

                    stale = await worker.call_tool('submit_for_review', {
                        'request_id': str(uuid.uuid4()), 'task_id': task_id,
                        'report': 'Wrong revision', 'repository': 'authfortress', 'revision': '0' * 40})
                    check('a revision that is not the submitted worktree HEAD fails closed', stale.isError)

                    unlisted = await worker.call_tool('get_file_owners', {
                        'paths': ['app/main.py'], 'repository': 'agenthub'})
                    check('a repository without a configured worktree is rejected', unlisted.isError)


if __name__ == '__main__':
    asyncio.run(run())
    failed = [name for name, ok, _ in results if not ok]
    print(f'\n{len(results) - len(failed)}/{len(results)} checks passed')
    if failed:
        print('failed: ' + ', '.join(failed))
    raise SystemExit(1 if failed else 0)
