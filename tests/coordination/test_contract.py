import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[2] / 'coordination_hub' / 'store.py'

class CoordinationContractTests(unittest.TestCase):
    def test_preflight_does_not_hold_database_write_lock(self):
        import uuid

        spec = importlib.util.spec_from_file_location('coordination_preflight', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            entered, release, other_done = Event(), Event(), Event()
            def preflight():
                entered.set()
                release.wait(10)
            def other():
                hub.mutate('development', str(uuid.uuid4()), 'heartbeat', {'status': 'working'})
                other_done.set()
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(hub.mutate, 'codex', str(uuid.uuid4()), 'create_task',
                                    {'title': 'Synthetic', 'description': 'Synthetic'}, preflight=preflight)
                try:
                    self.assertTrue(entered.wait(2))
                    second = pool.submit(other)
                    self.assertTrue(other_done.wait(2), 'Unrelated write was blocked by preflight')
                finally:
                    release.set()
                first.result()
                second.result()

    def test_parent_and_child_paths_conflict_in_both_directions(self):
        spec = importlib.util.spec_from_file_location('coordination_path_overlap', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            first = hub.create_task('codex', 'First', 'Synthetic')['id']
            second = hub.create_task('codex', 'Second', 'Synthetic')['id']
            hub.claim_task('security', first)
            hub.claim_task('development', second)
            lease = hub.lock_files('security', first, ['src'], 60)['lease_ids']
            with self.assertRaises(store.Conflict):
                hub.lock_files('development', second, ['src/app.py'], 60)
            hub.unlock_files('security', first, lease)
            hub.lock_files('security', first, ['src/app.py'], 60)
            with self.assertRaises(store.Conflict):
                hub.lock_files('development', second, ['src'], 60)

    def test_retried_expired_lease_never_reports_success(self):
        import uuid

        spec = importlib.util.spec_from_file_location('coordination_expired_retry', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            a = hub.create_task('codex', 'A', 'Synthetic')['id']
            b = hub.create_task('codex', 'B', 'Synthetic')['id']
            hub.claim_task('security', a)
            hub.claim_task('development', b)
            request = str(uuid.uuid4())
            payload = {'task_id': a, 'paths': ['docs/shared.md'], 'ttl': 60}
            with patch.object(store.time, 'time', return_value=1000):
                old = hub.mutate('security', request, 'lock_files', payload)
            with patch.object(store.time, 'time', return_value=1061):
                new = hub.lock_files('development', b, ['docs/shared.md'], 60)
                with self.assertRaises(store.Conflict):
                    hub.mutate('security', request, 'lock_files', payload)
                self.assertNotEqual(old['lease_ids'], new['lease_ids'])
                self.assertEqual(hub.file_owners(['docs/shared.md'])[0]['owner'], 'development')

    def test_existing_database_mode_never_creates_or_initializes(self):
        spec = importlib.util.spec_from_file_location('coordination_existing_store', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'hub.sqlite3'
            with self.assertRaises(sqlite3.OperationalError):
                store.Store(database, existing_only=True)
            self.assertFalse(database.exists())
            database.touch()
            with self.assertRaises(store.Conflict):
                store.Store(database, existing_only=True)
            self.assertEqual(database.stat().st_size, 0)
            hub = store.Store(database)
            task = hub.create_task('codex', 'Persistence', 'Synthetic')['id']
            existing = store.Store(database, existing_only=True)
            self.assertEqual(existing.get_task(task)['id'], task)
            database.unlink()
            with self.assertRaises(sqlite3.OperationalError):
                existing.get_task(task)
            with self.assertRaises(sqlite3.OperationalError):
                store.Store(database, existing_only=True)
            self.assertFalse(database.exists())

    def test_review_identifies_exact_submitted_revision(self):
        spec = importlib.util.spec_from_file_location('coordination_store_revision', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            task = hub.create_task('codex', 'Review commit', 'Synthetic')['id']
            hub.claim_task('development', task)
            revision = 'a' * 40
            submitted = hub.submit_for_review('development', task, 'Synthetic report',
                                               repository='nexuscore', revision=revision)
            evidence = hub.get_task(task)['reports'][0]
            self.assertEqual((evidence['repository'], evidence['revision']), ('nexuscore', revision))
            self.assertEqual(hub.review_task('codex', task, True, 'Reviewed', submitted['version'])['status'], 'completed')

    def test_stale_review_cannot_approve_resubmitted_work(self):
        spec = importlib.util.spec_from_file_location('coordination_store_stale_review', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            task = hub.create_task('codex', 'Review race', 'Synthetic')['id']
            hub.claim_task('development', task)
            first = hub.submit_for_review('development', task, 'First report', 'nexuscore', 'a' * 40)
            hub.review_task('codex', task, False, 'Fix', expected_version=first['version'])
            second = hub.submit_for_review('development', task, 'Updated report', 'nexuscore', 'b' * 40)
            with self.assertRaises(store.Conflict):
                hub.review_task('codex', task, True, 'Outdated approval', expected_version=first['version'])
            self.assertEqual(hub.get_task(task)['status'], 'in_review')
            self.assertEqual(hub.review_task('codex', task, True, 'Reviewed', expected_version=second['version'])['status'], 'completed')

    def test_heartbeat_and_lease_renewal_are_bounded(self):
        import uuid

        spec = importlib.util.spec_from_file_location('coordination_store_heartbeat', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            with patch.object(store.time, 'time', return_value=1000):
                task = hub.create_task('codex', 'Lease', 'Synthetic')['id']
                hub.claim_task('security', task)
                lease_id = hub.lock_files('security', task, ['docs/a.md'], 60)['lease_ids'][0]
                hub.mutate('security', str(uuid.uuid4()), 'heartbeat', {'status': 'working'})
                self.assertEqual(hub.get_agent_status('security')['status'], 'working')
            with patch.object(store.time, 'time', return_value=1050):
                request = str(uuid.uuid4())
                payload = {'task_id': task, 'lease_ids': [lease_id], 'ttl': 60}
                first = hub.mutate('security', request, 'renew_leases', payload)
                self.assertEqual(first, hub.mutate('security', request, 'renew_leases', payload))
                self.assertEqual(first['expires_at'], 1110)
                longer = hub.renew_leases('security', task, [lease_id], 120)
                shorter = hub.renew_leases('security', task, [lease_id], 60)
                self.assertEqual(longer['expires_at'], 1170)
                self.assertEqual(shorter['expires_at'], 1170)
                with self.assertRaises(store.Forbidden):
                    hub.renew_leases('development', task, [lease_id], 60)
            with patch.object(store.time, 'time', return_value=1171):
                self.assertEqual(hub.get_agent_status('security')['status'], 'offline')
                with self.assertRaises(store.Conflict):
                    hub.renew_leases('security', task, [lease_id], 60)

    def test_same_path_is_isolated_by_repository(self):
        spec = importlib.util.spec_from_file_location('coordination_store_repos', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            a = hub.create_task('codex', 'A', 'Synthetic')['id']
            b = hub.create_task('codex', 'B', 'Synthetic')['id']
            hub.claim_task('security', a)
            hub.claim_task('development', b)
            hub.lock_files('security', a, ['app/main.py'], 60, repository='authfortress')
            hub.lock_files('development', b, ['app/main.py'], 60, repository='agenthub')
            with self.assertRaises(store.Conflict):
                hub.lock_files('development', b, ['app/main.py'], 60, repository='authfortress')
            with self.assertRaises(ValueError):
                hub.lock_files('development', b, ['app/main.py'], 60, repository='unknown')

    def test_refuses_unknown_database_without_modifying_schema(self):
        spec = importlib.util.spec_from_file_location('coordination_store_schema', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hub.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE unrelated (value TEXT)')
            with self.assertRaises(store.Conflict):
                store.Store(path)
            with closing(sqlite3.connect(path)) as db:
                tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            self.assertEqual(tables, ['unrelated'])
            with closing(sqlite3.connect(path)) as db:
                db.execute('PRAGMA user_version = 1')
            with self.assertRaises(store.Conflict):
                store.Store(path)

    def test_task_and_inbox_pagination_never_hides_later_entries(self):
        spec = importlib.util.spec_from_file_location('coordination_store_pages', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            for index in range(3):
                hub.create_task('codex', f'Task {index}', 'Synthetic')
                hub.send_message('security', 'codex', f'Message {index}')
            first = hub.list_tasks(limit=2)
            second = hub.list_tasks(after=first[-1]['cursor'], limit=2)
            self.assertEqual([row['title'] for row in first + second], ['Task 0', 'Task 1', 'Task 2'])
            first = hub.inbox('codex', limit=2)
            second = hub.inbox('codex', after=first[-1]['cursor'], limit=2)
            self.assertEqual([row['body'] for row in first + second], ['Message 0', 'Message 1', 'Message 2'])
            with self.assertRaises(ValueError):
                hub.list_tasks(limit=101)

    def test_review_reports_are_paginated(self):
        spec = importlib.util.spec_from_file_location('coordination_store_reports', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            task = hub.create_task('codex', 'Review', 'Synthetic')['id']
            hub.claim_task('development', task)
            submitted = hub.submit_for_review('development', task, 'First', 'nexuscore', 'a' * 40)
            hub.review_task('codex', task, False, 'Fix', submitted['version'])
            hub.submit_for_review('development', task, 'Second', 'nexuscore', 'b' * 40)
            first = hub.get_task(task, reports_limit=2)['reports']
            second = hub.get_task(task, reports_after=first[-1]['cursor'], reports_limit=2)['reports']
            self.assertEqual([row['body'] for row in first + second], ['First', 'Fix', 'Second'])

    def test_concurrent_process_reservations_have_one_winner(self):
        spec = importlib.util.spec_from_file_location('coordination_store_lock_process', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hub.sqlite3'
            hub = store.Store(path)
            tasks = [hub.create_task('codex', name, 'Synthetic')['id'] for name in ('A', 'B')]
            for agent, task in zip(('security', 'development'), tasks):
                hub.claim_task(agent, task)
            code = '''import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('store',sys.argv[1]); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
hub=m.Store(sys.argv[2]); print('ready',flush=True); input()
try:
    hub.lock_files(sys.argv[4],sys.argv[3],['src/shared.py'],60); print(json.dumps({'result':'acquired'}),flush=True)
except m.Conflict:
    print(json.dumps({'result':'conflict'}),flush=True)
'''
            procs = [subprocess.Popen([sys.executable, '-B', '-c', code, str(MODULE), str(path), task, agent],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for agent, task in zip(('security', 'development'), tasks)]
            try:
                for proc in procs:
                    self.assertEqual(proc.stdout.readline().strip(), 'ready')
                for proc in procs:
                    proc.stdin.write('\n')
                    proc.stdin.flush()
                outcomes = []
                for proc in procs:
                    stdout, stderr = proc.communicate(timeout=10)
                    self.assertEqual(proc.returncode, 0, stderr)
                    outcomes.append(json.loads(stdout)['result'])
                self.assertCountEqual(outcomes, ['acquired', 'conflict'])
            finally:
                for proc in procs:
                    if proc.poll() is None:
                        proc.kill()
                        proc.communicate()

    def test_concurrent_process_claims_are_serialized(self):
        spec = importlib.util.spec_from_file_location('coordination_store_process', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hub.sqlite3'
            hub = store.Store(path)
            task_id = hub.create_task('codex', 'Process race', 'Synthetic task')['id']
            code = '''import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('store',sys.argv[1]); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
hub=m.Store(sys.argv[2]); print('ready',flush=True); input()
try:
    task=hub.claim_task(sys.argv[4],sys.argv[3]); print(json.dumps({'result':'claimed','owner':task['owner']}),flush=True)
except m.Conflict:
    print(json.dumps({'result':'conflict'}),flush=True)
'''
            procs = [subprocess.Popen([sys.executable, '-B', '-c', code, str(MODULE), str(path), task_id, actor],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for actor in ('security', 'development')]
            try:
                for proc in procs:
                    self.assertEqual(proc.stdout.readline().strip(), 'ready')
                for proc in procs:
                    proc.stdin.write('\n')
                    proc.stdin.flush()
                outcomes = []
                for proc in procs:
                    stdout, stderr = proc.communicate(timeout=10)
                    self.assertEqual(proc.returncode, 0, stderr)
                    outcomes.append(json.loads(stdout)['result'])
                self.assertCountEqual(outcomes, ['claimed', 'conflict'])
            finally:
                for proc in procs:
                    if proc.poll() is None:
                        proc.kill()
                        proc.communicate()

    def test_lost_response_retry_is_atomic_and_does_not_duplicate(self):
        import uuid

        spec = importlib.util.spec_from_file_location('coordination_store_retry', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            request_id = str(uuid.uuid4())
            payload = {'title': 'Retry', 'description': 'Synthetic task'}
            first = hub.mutate('codex', request_id, 'create_task', payload)
            second = hub.mutate('codex', request_id, 'create_task', payload)
            self.assertEqual(first, second)
            self.assertEqual(len(hub.list_tasks()), 1)
            with self.assertRaises(store.Conflict):
                hub.mutate('codex', request_id, 'create_task', {'title': 'Different', 'description': 'Synthetic task'})
            def unavailable():
                raise OSError('Path changed after commit')
            self.assertEqual(first, hub.mutate('codex', request_id, 'create_task', payload, preflight=unavailable))

    def test_retry_after_process_exits_after_commit(self):
        import uuid

        spec = importlib.util.spec_from_file_location('coordination_store_crash', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hub.sqlite3'
            hub = store.Store(path)
            request_id = str(uuid.uuid4())
            payload = {'title': 'Crash recovery', 'description': 'Synthetic task'}
            code = '''import importlib.util,os,sys
spec=importlib.util.spec_from_file_location('store',sys.argv[1]); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.Store(sys.argv[2]).mutate('codex',sys.argv[3],'create_task',{'title':'Crash recovery','description':'Synthetic task'})
os._exit(0)
'''
            result = subprocess.run([sys.executable, '-B', '-c', code, str(MODULE), str(path), request_id],
                                    capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            recovered = hub.mutate('codex', request_id, 'create_task', payload)
            self.assertEqual(len(hub.list_tasks()), 1)
            self.assertEqual(hub.list_tasks()[0]['id'], recovered['id'])

    def test_simultaneous_claim_has_one_winner(self):
        self.assertTrue(MODULE.exists(), 'Coordination store must exist')
        spec = importlib.util.spec_from_file_location('coordination_store_race', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'hub.sqlite3'
            hub = store.Store(path)
            task_id = hub.create_task('codex', 'Race', 'Synthetic task')['id']
            gate = Barrier(2)

            def claim(actor):
                other = store.Store(path)
                gate.wait(timeout=5)
                try:
                    other.claim_task(actor, task_id)
                    return 'claimed'
                except store.Conflict:
                    return 'conflict'

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(claim, ('security', 'development')))
            self.assertCountEqual(results, ['claimed', 'conflict'])

    def test_task_review_and_owner_checks(self):
        self.assertTrue(MODULE.exists(), 'Coordination store must exist')
        spec = importlib.util.spec_from_file_location('coordination_store', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            task = hub.create_task('codex', 'Check integration', 'Synthetic task')
            task_id = task['id']
            with self.assertRaises(store.Forbidden):
                hub.claim_task('codex', task_id)
            hub.claim_task('development', task_id)
            with self.assertRaises(store.Conflict):
                hub.claim_task('security', task_id)
            with self.assertRaises(store.Forbidden):
                hub.submit_for_review('security', task_id, 'No work performed', 'nexuscore', 'a' * 40)
            submitted = hub.submit_for_review('development', task_id, 'Implemented and tested', 'nexuscore', 'a' * 40)
            with self.assertRaises(store.Forbidden):
                hub.review_task('development', task_id, True, 'Self review', submitted['version'])
            hub.review_task('codex', task_id, False, 'Please fix the test', submitted['version'])
            submitted = hub.submit_for_review('development', task_id, 'Test fixed', 'nexuscore', 'b' * 40)
            result = hub.review_task('codex', task_id, True, 'Reviewed', submitted['version'])
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(hub.list_tasks()[0]['owner'], 'development')

    def test_messages_and_lease_conflicts(self):
        self.assertTrue(MODULE.exists(), 'Coordination store must exist')
        spec = importlib.util.spec_from_file_location('coordination_store', MODULE)
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        with tempfile.TemporaryDirectory() as folder:
            hub = store.Store(Path(folder) / 'hub.sqlite3')
            task = hub.create_task('codex', 'Synthetic work', 'No project files')
            hub.claim_task('development', task['id'])
            hub.send_message('development', 'codex', 'Ready for review')
            self.assertEqual(hub.inbox('codex')[0]['sender'], 'development')
            lease = hub.lock_files('development', task['id'], ['docs/example.md'], 60)
            other = hub.create_task('codex', 'Other work', 'Synthetic task')
            hub.claim_task('security', other['id'])
            with self.assertRaises(store.Conflict):
                hub.lock_files('security', other['id'], ['docs/EXAMPLE.md'], 60)
            for path in ('../secrets', '.env', '.git/config', 'C:/windows/file',
                         'docs/SHORTN~1.txt', 'docs/name?.txt', 'docs/file\n.txt',
                         'docs/CON.txt', 'docs/example.txt:secret', 'docs/тест.txt'):
                with self.assertRaises(ValueError):
                    hub.lock_files('development', task['id'], [path], 60)
            with self.assertRaises(ValueError):
                hub.unlock_files('development', task['id'], lease['lease_ids'] * 2)
            self.assertEqual(len(hub.file_owners(['docs/example.md'])), 1)
            hub.unlock_files('development', task['id'], lease['lease_ids'])
            self.assertEqual(hub.file_owners(['docs/example.md']), [])

if __name__ == '__main__':
    unittest.main()
