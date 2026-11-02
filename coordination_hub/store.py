"""Transactional coordination state for trusted local agents."""
import hashlib
import json
import ntpath
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

AGENTS = frozenset({'security', 'development', 'codex'})
REPOSITORIES = frozenset({'nexuscore', 'authfortress', 'webhook_manager', 'agenthub', 'eventpipe', 'pipewatch'})
APPLICATION_ID = 1314419522
SCHEMA_COLUMNS = {
    'tasks': ['id', 'title', 'description', 'creator', 'owner', 'status', 'version', 'created_at', 'updated_at'],
    'messages': ['id', 'sender', 'recipient', 'body', 'created_at'],
    'leases': ['repository', 'path', 'task_id', 'owner', 'lease_id', 'expires_at'],
    'reports': ['id', 'task_id', 'author', 'kind', 'body', 'repository', 'revision', 'created_at'],
    'events': ['seq', 'actor', 'kind', 'entity_id', 'created_at'],
    'requests': ['actor', 'request_id', 'fingerprint', 'result'],
    'agent_status': ['agent', 'status', 'last_seen'],
}

class Forbidden(Exception):
    pass

class Conflict(Exception):
    pass

def _agent(value):
    if value not in AGENTS:
        raise Forbidden('Unknown agent')
    return value

def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > limit:
        raise ValueError('Invalid text')
    return value.strip()

def _page(after, limit):
    if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid page')

def validate_schema(db):
    """Reject unrecognized schema; these checks do not establish authenticity."""
    if db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
        raise Conflict('Unknown database application')
    if db.execute('PRAGMA user_version').fetchone()[0] != 4:
        raise Conflict('Unknown database version')
    names = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if names != set(SCHEMA_COLUMNS):
        raise Conflict('Unexpected database schema')
    for table, expected in SCHEMA_COLUMNS.items():
        columns = [row[1] for row in db.execute(f'PRAGMA table_info({table})')]
        if columns != expected:
            raise Conflict('Unexpected database schema')
    triggers = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    if triggers != {'events_no_update', 'events_no_delete'}:
        raise Conflict('Unexpected database schema')

def _path(value):
    if not isinstance(value, str) or not value or len(value) > 512 or '\\' in value or ':' in value or '\x00' in value:
        raise ValueError('Invalid path')
    parts = value.split('/')
    if any(not p or p in ('.', '..') or p.endswith((' ', '.')) for p in parts):
        raise ValueError('Invalid path')
    for part in parts:
        if not re.fullmatch(r'[A-Za-z0-9_. -]+', part, flags=re.ASCII):
            raise ValueError('Unsupported path characters')
        folded = part.casefold()
        stem = folded.split('.')[0]
        if folded == '.git' or folded == '.worktrees' or folded == '.env' or folded.startswith('.env.'):
            raise ValueError('Forbidden path')
        if stem in {'con', 'prn', 'aux', 'nul'} or re.fullmatch(r'(com|lpt)[1-9]', stem):
            raise ValueError('Reserved path')
    if ntpath.isabs(value):
        raise ValueError('Invalid path')
    return value.casefold()

class Store:
    def __init__(self, path, *, existing_only=False):
        self.path = str(path)
        self.existing_only = existing_only
        self._active = ContextVar('coordination_transaction', default=None)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            application_id = db.execute('PRAGMA application_id').fetchone()[0]
            if existing_only:
                validate_schema(db)
                return
            if version == 4:
                validate_schema(db)
                return
            objects = db.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone()
            if version != 0 or application_id != 0 or objects:
                raise Conflict('Unknown database schema')
            statements = (
                '''CREATE TABLE tasks (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
                    creator TEXT NOT NULL, owner TEXT, status TEXT NOT NULL,
                    version INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
                )''',
                '''CREATE TABLE messages (
                    id TEXT PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL,
                    body TEXT NOT NULL, created_at INTEGER NOT NULL
                )''',
                'CREATE INDEX messages_recipient ON messages(recipient, created_at)',
                '''CREATE TABLE leases (
                    repository TEXT NOT NULL, path TEXT NOT NULL, task_id TEXT NOT NULL, owner TEXT NOT NULL,
                    lease_id TEXT NOT NULL UNIQUE, expires_at INTEGER NOT NULL, PRIMARY KEY(repository, path)
                )''',
                '''CREATE TABLE reports (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, author TEXT NOT NULL,
                    kind TEXT NOT NULL, body TEXT NOT NULL, repository TEXT NOT NULL,
                    revision TEXT NOT NULL, created_at INTEGER NOT NULL
                )''',
                '''CREATE TABLE events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, kind TEXT NOT NULL,
                    entity_id TEXT NOT NULL, created_at INTEGER NOT NULL
                )''',
                '''CREATE TABLE requests (
                    actor TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    result TEXT NOT NULL, PRIMARY KEY(actor, request_id)
                )''',
                '''CREATE TABLE agent_status (
                    agent TEXT PRIMARY KEY, status TEXT NOT NULL, last_seen INTEGER NOT NULL
                )''',
                '''CREATE TRIGGER events_no_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'Events are append only'); END''',
                '''CREATE TRIGGER events_no_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'Events are append only'); END''',
            )
            for statement in statements:
                db.execute(statement)
            db.execute(f'PRAGMA application_id = {APPLICATION_ID}')
            db.execute('PRAGMA user_version = 4')

    @contextmanager
    def _connect(self):
        active = self._active.get()
        if active is not None:
            yield active
            return
        target = Path(self.path).absolute().as_uri() + '?mode=rw' if self.existing_only else self.path
        db = sqlite3.connect(target, timeout=5, isolation_level='IMMEDIATE', uri=self.existing_only)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout = 5000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def mutate(self, actor, request_id, operation, payload, *, preflight=None):
        _agent(actor)
        try:
            if str(uuid.UUID(request_id)) != request_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Invalid request ID') from None
        permitted = {'create_task', 'claim_task', 'submit_for_review', 'review_task',
                     'send_message', 'lock_files', 'unlock_files', 'renew_leases', 'heartbeat'}
        if operation not in permitted or not isinstance(payload, dict):
            raise ValueError('Invalid operation')
        canonical = json.dumps({'operation': operation, 'payload': payload}, sort_keys=True,
                               ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        fingerprint = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        def previous_result(db):
            previous = db.execute('SELECT fingerprint,result FROM requests WHERE actor=? AND request_id=?',
                                  (actor, request_id)).fetchone()
            if not previous:
                return None
            if previous['fingerprint'] != fingerprint:
                raise Conflict('Request ID already used')
            result = json.loads(previous['result'])
            if operation in {'lock_files', 'renew_leases'}:
                now = int(time.time())
                if result['expires_at'] <= now:
                    raise Conflict('Previous lease result expired')
                for lease_id in result['lease_ids']:
                    lease = db.execute('SELECT owner,task_id,expires_at FROM leases WHERE lease_id=?',
                                       (lease_id,)).fetchone()
                    if (not lease or lease['owner'] != actor or lease['task_id'] != payload['task_id']
                            or lease['expires_at'] <= now):
                        raise Conflict('Previous lease result no longer valid')
            return result

        with self._connect() as db:
            previous = previous_result(db)
            if previous is not None:
                return previous
        if preflight is not None:
            preflight()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = previous_result(db)
            if previous is not None:
                return previous
            token = self._active.set(db)
            try:
                result = getattr(self, operation)(actor, **payload)
            finally:
                self._active.reset(token)
            db.execute('INSERT INTO requests VALUES (?,?,?,?)',
                       (actor, request_id, fingerprint, json.dumps(result, ensure_ascii=False)))
            return result

    @staticmethod
    def _event(db, actor, kind, entity):
        db.execute('INSERT INTO events(actor,kind,entity_id,created_at) VALUES (?,?,?,?)',
                   (actor, kind, entity, int(time.time())))

    @staticmethod
    def _task(db, task_id):
        row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if row is None:
            raise ValueError('Task not found')
        return row

    def create_task(self, actor, title, description):
        _agent(actor)
        title, description = _text(title, 200), _text(description, 16384)
        task_id, now = str(uuid.uuid4()), int(time.time())
        with self._connect() as db:
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)',
                       (task_id, title, description, actor, None, 'open', 1, now, now))
            self._event(db, actor, 'task.created', task_id)
            return dict(self._task(db, task_id))

    def list_tasks(self, after=0, limit=50):
        _page(after, limit)
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT rowid AS cursor,* FROM tasks WHERE rowid>? ORDER BY rowid LIMIT ?', (after, limit))]

    def get_task(self, task_id, reports_after=0, reports_limit=50):
        _page(reports_after, reports_limit)
        with self._connect() as db:
            task = dict(self._task(db, task_id))
            task['reports'] = [dict(row) for row in db.execute(
                'SELECT rowid AS cursor,* FROM reports WHERE task_id=? AND rowid>? ORDER BY rowid LIMIT ?',
                (task_id, reports_after, reports_limit))]
            return task

    def claim_task(self, actor, task_id):
        _agent(actor)
        if actor == 'codex':
            raise Forbidden('Reviewer cannot claim a task')
        with self._connect() as db:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            row = self._task(db, task_id)
            if row['status'] != 'open':
                raise Conflict('Task unavailable')
            db.execute("UPDATE tasks SET owner=?,status='in_progress',version=version+1,updated_at=? WHERE id=?",
                       (actor, int(time.time()), task_id))
            self._event(db, actor, 'task.claimed', task_id)
            return dict(self._task(db, task_id))

    def submit_for_review(self, actor, task_id, report, repository, revision):
        _agent(actor)
        report = _text(report, 16384)
        if repository not in REPOSITORIES or not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision):
            raise ValueError('Invalid repository or revision')
        with self._connect() as db:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            task = self._task(db, task_id)
            if task['owner'] != actor:
                raise Forbidden('Not task owner')
            if task['status'] != 'in_progress':
                raise Conflict('Task not in progress')
            now = int(time.time())
            db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)',
                       (str(uuid.uuid4()), task_id, actor, 'completion', report, repository, revision, now))
            db.execute("UPDATE tasks SET status='in_review',version=version+1,updated_at=? WHERE id=?", (now, task_id))
            self._event(db, actor, 'task.submitted', task_id)
            return dict(self._task(db, task_id))

    def review_task(self, actor, task_id, approved, report, expected_version):
        _agent(actor)
        if actor != 'codex':
            raise Forbidden('Only codex can review')
        if type(approved) is not bool:
            raise ValueError('Invalid decision')
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError('Invalid version')
        report = _text(report, 16384)
        with self._connect() as db:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            task = self._task(db, task_id)
            if task['owner'] == actor:
                raise Forbidden('Self review forbidden')
            if task['status'] != 'in_review':
                raise Conflict('Task not in review')
            if task['version'] != expected_version:
                raise Conflict('Task version changed')
            evidence = db.execute("SELECT repository,revision FROM reports WHERE task_id=? AND kind='completion' ORDER BY rowid DESC LIMIT 1", (task_id,)).fetchone()
            if evidence is None:
                raise Conflict('Completion report missing')
            now = int(time.time())
            db.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?,?)',
                       (str(uuid.uuid4()), task_id, actor, 'approved' if approved else 'changes_requested', report,
                        evidence['repository'], evidence['revision'], now))
            db.execute('UPDATE tasks SET status=?,version=version+1,updated_at=? WHERE id=?',
                       ('completed' if approved else 'in_progress', now, task_id))
            self._event(db, actor, 'task.reviewed', task_id)
            return dict(self._task(db, task_id))

    def send_message(self, actor, recipient, body):
        _agent(actor)
        _agent(recipient)
        body = _text(body, 16384)
        message_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?)', (message_id, actor, recipient, body, int(time.time())))
            self._event(db, actor, 'message.sent', message_id)
        return {'id': message_id}

    def inbox(self, actor, after=0, limit=50):
        _agent(actor)
        _page(after, limit)
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT rowid AS cursor,* FROM messages WHERE recipient=? AND rowid>? ORDER BY rowid LIMIT ?',
                (actor, after, limit))]

    def heartbeat(self, actor, status):
        _agent(actor)
        if status not in {'idle', 'working', 'blocked'}:
            raise ValueError('Invalid status')
        now = int(time.time())
        with self._connect() as db:
            db.execute('INSERT INTO agent_status VALUES (?,?,?) ON CONFLICT(agent) '
                       'DO UPDATE SET status=excluded.status,last_seen=excluded.last_seen', (actor, status, now))
            self._event(db, actor, 'agent.heartbeat', actor)
        return {'agent': actor, 'status': status, 'last_seen': now}

    def get_agent_status(self, agent):
        _agent(agent)
        with self._connect() as db:
            row = db.execute('SELECT * FROM agent_status WHERE agent=?', (agent,)).fetchone()
        if row is None:
            return {'agent': agent, 'status': 'offline', 'last_seen': None}
        result = dict(row)
        if int(time.time()) - result['last_seen'] > 90:
            result['status'] = 'offline'
        return result

    def renew_leases(self, actor, task_id, lease_ids, ttl):
        _agent(actor)
        if (not isinstance(lease_ids, list) or not 1 <= len(lease_ids) <= 100 or
                len(set(lease_ids)) != len(lease_ids) or type(ttl) is not int or not 60 <= ttl <= 3600):
            raise ValueError('Invalid lease request')
        with self._connect() as db:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            task = self._task(db, task_id)
            if task['owner'] != actor:
                raise Forbidden('Not task owner')
            if task['status'] != 'in_progress':
                raise Conflict('Task not in progress')
            now = int(time.time())
            for lease_id in lease_ids:
                row = db.execute('SELECT * FROM leases WHERE lease_id=?', (lease_id,)).fetchone()
                if not row or row['owner'] != actor or row['task_id'] != task_id:
                    raise Forbidden('Lease unavailable')
                if row['expires_at'] <= now:
                    raise Conflict('Lease expired')
            expires_at = now + ttl
            for lease_id in lease_ids:
                db.execute('UPDATE leases SET expires_at=MAX(expires_at,?) WHERE lease_id=?', (expires_at, lease_id))
                self._event(db, actor, 'lease.renewed', lease_id)
            earliest_expiry = min(db.execute('SELECT expires_at FROM leases WHERE lease_id=?', (lease_id,)).fetchone()[0]
                                  for lease_id in lease_ids)
            return {'lease_ids': lease_ids, 'expires_at': earliest_expiry}

    def lock_files(self, actor, task_id, paths, ttl, repository='nexuscore'):
        _agent(actor)
        if repository not in REPOSITORIES:
            raise ValueError('Unknown repository')
        if not isinstance(paths, list) or not 1 <= len(paths) <= 100 or type(ttl) is not int or not 60 <= ttl <= 3600:
            raise ValueError('Invalid lease request')
        keys = [_path(path) for path in paths]
        if len(set(keys)) != len(keys):
            raise ValueError('Duplicate paths')
        if any(a.startswith(b + '/') or b.startswith(a + '/') for i, a in enumerate(keys) for b in keys[i + 1:]):
            raise ValueError('Overlapping paths')
        with self._connect() as db:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            now = int(time.time())
            task = self._task(db, task_id)
            if task['owner'] != actor:
                raise Forbidden('Not task owner')
            if task['status'] != 'in_progress':
                raise Conflict('Task not in progress')
            for key in keys:
                row = db.execute('SELECT 1 FROM leases WHERE repository=? AND expires_at>? AND '
                                 '(path=? OR substr(path,1,length(?)+1)=? || \'/\' OR '
                                 'substr(?,1,length(path)+1)=path || \'/\') LIMIT 1',
                                 (repository, now, key, key, key, key)).fetchone()
                if row:
                    raise Conflict('File already reserved')
            lease_ids = []
            for key in keys:
                lease_id = str(uuid.uuid4())
                lease_ids.append(lease_id)
                db.execute('DELETE FROM leases WHERE repository=? AND path=? AND expires_at<=?', (repository, key, now))
                db.execute('INSERT INTO leases VALUES (?,?,?,?,?,?)', (repository, key, task_id, actor, lease_id, now + ttl))
                self._event(db, actor, 'lease.acquired', lease_id)
            return {'lease_ids': lease_ids, 'expires_at': now + ttl}

    def unlock_files(self, actor, task_id, lease_ids):
        _agent(actor)
        if (not isinstance(lease_ids, list) or not 1 <= len(lease_ids) <= 100 or
                len(set(lease_ids)) != len(lease_ids)):
            raise ValueError('Invalid lease request')
        with self._connect() as db:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            for lease_id in lease_ids:
                row = db.execute('SELECT * FROM leases WHERE lease_id=?', (lease_id,)).fetchone()
                if not row or row['owner'] != actor or row['task_id'] != task_id:
                    raise Forbidden('Lease unavailable')
            for lease_id in lease_ids:
                db.execute('DELETE FROM leases WHERE lease_id=?', (lease_id,))
                self._event(db, actor, 'lease.released', lease_id)
            return {'released': len(lease_ids)}

    def file_owners(self, paths, repository='nexuscore'):
        if repository not in REPOSITORIES:
            raise ValueError('Unknown repository')
        if not isinstance(paths, list) or not 1 <= len(paths) <= 100:
            raise ValueError('Invalid paths')
        keys = [_path(path) for path in paths]
        now = int(time.time())
        with self._connect() as db:
            return [dict(row) for key in keys for row in db.execute(
                'SELECT * FROM leases WHERE repository=? AND expires_at>? AND '
                '(path=? OR substr(path,1,length(?)+1)=? || \'/\' OR '
                'substr(?,1,length(path)+1)=path || \'/\')', (repository, now, key, key, key, key))]
