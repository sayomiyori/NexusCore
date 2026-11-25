"""Relay rejected/dead-letter state machine: bounded retry, backoff and read-only listing."""

import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx

from scripts import relay_observability as relay

# Patching relay.httpx.Client patches the shared module, so keep the real class for factories.
REAL_CLIENT = httpx.Client

TENANT, BOT = UUID(int=10), UUID(int=20)
ORIGINS = {"agent": "http://127.0.0.1:1", "eventpipe": "http://127.0.0.1:2", "pipewatch": "http://127.0.0.1:3"}
JOB = {"id": str(UUID(int=100)), "event_id": str(UUID(int=200)), "state": "completed",
       "attempts": 1, "updated_at": "2026-10-22T10:00:00Z"}
PAST = "2000-01-01T00:00:00+00:00"


def response(data, status=200):
    return httpx.Response(status, stream=httpx.ByteStream(json.dumps(data).encode()))


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.sqlite"
        self.db = relay.open_state(self.path, "binding")
        self.addCleanup(self.db.close)
        self.posts = []
        self.status = {"eventpipe": 200, "pipewatch": 200}
        self.transport_failure = set()

        def handle(request):
            if request.method == "GET":
                return response({"items": [JOB], "next_cursor": None})
            role = "eventpipe" if request.url.port == 2 else "pipewatch"
            self.posts.append(role)
            if role in self.transport_failure:
                raise httpx.ReadTimeout("private-transport-details")
            status = self.status[role]
            if status != 200:
                return response({"detail": "private-receiver-detail"}, status)
            return response({"status": "accepted", "event_id": str(uuid4())} if role == "eventpipe"
                            else {"status": "accepted", "count": 1})

        self.handle = handle
        self.client = httpx.Client(transport=httpx.MockTransport(handle), trust_env=False)
        self.addCleanup(self.client.close)
        self.worker = relay.Relay(self.db, self.client, ORIGINS, TENANT, BOT, "synthetic-only")

    def rows(self, db=None):
        connection = db or self.db
        return {sink: (state, attempts, scheduled, status) for sink, state, attempts, scheduled, status
                in connection.execute("SELECT sink,state,attempts,next_attempt_at,last_status FROM relay_deliveries")}

    def make_due(self):
        self.db.execute("UPDATE relay_deliveries SET next_attempt_at=? WHERE state='rejected'", (PAST,))
        self.db.commit()

    def test_definite_rejection_waits_for_backoff_then_succeeds_exactly_once(self):
        self.status["eventpipe"] = 503
        counts = self.worker.sweep()
        self.assertEqual(counts, {"pending": 0, "accepted": 1, "unknown": 0, "rejected": 1})
        state, attempts, scheduled, status = self.rows()["eventpipe"]
        self.assertEqual((state, attempts, status), ("rejected", 1, "503"))
        self.assertIsNotNone(scheduled)
        self.assertGreater(datetime.fromisoformat(scheduled), datetime.now(UTC))
        self.assertEqual(len(self.posts), 2)

        # Not due yet: no resend, no new attempt counted.
        self.assertEqual(self.worker.sweep()["rejected"], 1)
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(self.rows()["eventpipe"][1], 1)

        self.make_due()
        self.status["eventpipe"] = 200
        self.assertEqual(self.worker.sweep(), {"pending": 0, "accepted": 2, "unknown": 0})
        self.assertEqual(self.posts.count("eventpipe"), 2)
        state, attempts, scheduled, status = self.rows()["eventpipe"]
        self.assertEqual((state, attempts, scheduled, status), ("accepted", 2, None, None))

    def test_backoff_schedule_doubles_caps_and_stays_inside_jitter_bounds(self):
        for attempt in range(1, relay.MAX_ATTEMPTS + 1):
            base = min(relay.RETRY_CAP_SECONDS, relay.RETRY_BASE_SECONDS * 2 ** (attempt - 1))
            with patch.object(relay.random, "uniform", return_value=1.0):
                self.assertEqual(relay.retry_delay(attempt), base)
            for _ in range(20):
                delay = relay.retry_delay(attempt)
                self.assertGreaterEqual(delay, base * 0.8)
                self.assertLessEqual(delay, base * 1.2)
        self.assertEqual(min(relay.RETRY_CAP_SECONDS, 5 * 2 ** 7), 300)

    def test_pipewatch_backlog_is_retried_but_its_503_stays_ambiguous(self):
        self.status["pipewatch"] = 429
        self.assertEqual(self.worker.sweep()["rejected"], 1)
        self.assertEqual(self.rows()["pipewatch"][:2], ("rejected", 1))

        self.make_due()
        self.status["pipewatch"] = 503
        counts = self.worker.sweep()
        self.assertEqual(counts, {"pending": 0, "accepted": 1, "unknown": 1})
        self.assertEqual(self.rows()["pipewatch"], ("unknown", 2, None, None))

        # Ambiguous rows are never selected again, even long after their last attempt.
        self.make_due()
        self.status["pipewatch"] = 200
        self.worker.sweep()
        self.assertEqual(self.posts.count("pipewatch"), 2)
        self.assertEqual(self.rows()["pipewatch"][0], "unknown")

    def test_transport_failure_is_unknown_and_never_retried(self):
        self.transport_failure.add("eventpipe")
        self.assertEqual(self.worker.sweep(), {"pending": 0, "accepted": 1, "unknown": 1})
        self.assertEqual(self.rows()["eventpipe"], ("unknown", 1, None, None))
        self.transport_failure.clear()
        self.worker.sweep()
        self.assertEqual(self.posts.count("eventpipe"), 1)

    def test_attempt_limit_dead_letters_and_stops_sending(self):
        self.status["eventpipe"] = 503
        for attempt in range(1, relay.MAX_ATTEMPTS + 1):
            self.worker.sweep()
            if attempt < relay.MAX_ATTEMPTS:
                self.assertEqual(self.rows()["eventpipe"][0], "rejected")
                self.make_due()
        state, attempts, scheduled, status = self.rows()["eventpipe"]
        self.assertEqual((state, attempts, scheduled, status), ("dead_letter", relay.MAX_ATTEMPTS, None, "503"))
        sent = self.posts.count("eventpipe")
        self.assertEqual(sent, relay.MAX_ATTEMPTS)
        self.assertEqual(self.worker.sweep()["dead_letter"], 1)
        self.assertEqual(self.posts.count("eventpipe"), sent)
        self.assertEqual(relay.dead_letters(self.db),
                         [{"event_id": self.db.execute("SELECT event_id FROM relay_deliveries WHERE sink='eventpipe'")
                           .fetchone()[0], "sink": "eventpipe", "attempts": relay.MAX_ATTEMPTS, "last_status": "503"}])

    def test_pre_retry_state_migrates_preserving_rows_and_stays_readable_read_only(self):
        legacy = Path(self.directory.name) / "legacy.sqlite"
        db = sqlite3.connect(legacy)
        with db:
            db.executescript("""
                CREATE TABLE relay_meta(binding TEXT NOT NULL);
                CREATE TABLE relay_events(id TEXT PRIMARY KEY, envelope TEXT NOT NULL);
                CREATE TABLE relay_deliveries(
                    event_id TEXT NOT NULL REFERENCES relay_events(id), sink TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','unknown','accepted')),
                    receipt TEXT, PRIMARY KEY(event_id,sink));
            """)
            db.execute("INSERT INTO relay_meta VALUES ('binding')")
            event = relay.envelope(relay.Job.model_validate(JOB), TENANT, BOT)
            db.execute("INSERT INTO relay_events VALUES (?,?)", (event["event_id"], json.dumps(event)))
            db.execute("INSERT INTO relay_deliveries VALUES (?,'eventpipe','accepted','remote')", (event["event_id"],))
            db.execute("INSERT INTO relay_deliveries VALUES (?,'pipewatch','unknown',NULL)", (event["event_id"],))
        db.close()

        before = legacy.read_bytes()
        with contextlib.closing(relay.open_state(legacy, "binding", read_only=True)) as reader:
            # Read-only access never migrates and reports no dead letters on the old schema.
            self.assertEqual(relay.dead_letters(reader), [])
        self.assertEqual(legacy.read_bytes(), before)

        migrated = relay.open_state(legacy, "binding")
        self.addCleanup(migrated.close)
        self.assertEqual(self.rows(migrated)["eventpipe"][:2], ("accepted", 0))
        self.assertEqual(self.rows(migrated)["pipewatch"][0], "unknown")
        with self.assertRaises(ValueError):
            relay.open_state(legacy, "other-binding")

    def test_cli_dead_letter_listing_needs_no_bearer_and_writes_nothing(self):
        event = relay.envelope(relay.Job.model_validate(JOB), TENANT, BOT)
        with self.db:
            self.db.execute("INSERT INTO relay_events VALUES (?,?)", (event["event_id"], json.dumps(event)))
            self.db.execute("INSERT INTO relay_deliveries(event_id,sink,state,attempts,last_status) "
                            "VALUES (?,'eventpipe','dead_letter',8,'503')", (event["event_id"],))
        before = self.path.read_bytes()
        output = io.StringIO()
        with patch.dict(os.environ, {"NEXUS_EVENTS_TOKEN": ""}), contextlib.redirect_stdout(output):
            self.assertEqual(relay.main(["--dead-letters", "--state", str(self.path)]), 0)
        listed = json.loads(output.getvalue())
        self.assertEqual(listed, [{"event_id": event["event_id"], "sink": "eventpipe",
                                   "attempts": 8, "last_status": "503"}])
        self.assertNotIn("synthetic-only", output.getvalue())
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(ValueError):
            relay.open_state(Path(self.directory.name) / "absent.sqlite", None, read_only=True)

    def fresh_clients(self):
        # main() closes the client it builds, so every invocation needs a new instance.
        return REAL_CLIENT(transport=httpx.MockTransport(self.handle), trust_env=False)

    def test_cli_sweep_returns_nonzero_for_rejected_and_creates_retry_state(self):
        path = Path(self.directory.name) / "cli.sqlite"
        args = ["--agent-origin", ORIGINS["agent"], "--eventpipe-origin", ORIGINS["eventpipe"],
                "--pipewatch-origin", ORIGINS["pipewatch"], "--tenant-id", str(TENANT),
                "--bot-id", str(BOT), "--state", str(path)]
        self.status["eventpipe"] = 503
        output = io.StringIO()
        with (patch.dict(os.environ, {"NEXUS_EVENTS_TOKEN": "synthetic-only"}),
              patch.object(relay.httpx, "Client", side_effect=lambda *a, **k: self.fresh_clients()),
              contextlib.redirect_stdout(output)):
            self.assertEqual(relay.main(args), 1)
        self.assertEqual(json.loads(output.getvalue())["rejected"], 1)
        with contextlib.closing(sqlite3.connect(path)) as db:
            state, attempts, scheduled, status = self.rows(db)["eventpipe"]
        self.assertEqual((state, attempts, status), ("rejected", 1, "503"))
        self.assertIsNotNone(scheduled)

        # An interval run treats a scheduled rejection as work in progress, not a fatal exit.
        self.make_cli_due(path)
        self.status["eventpipe"] = 200
        output = io.StringIO()
        with (patch.dict(os.environ, {"NEXUS_EVENTS_TOKEN": "synthetic-only"}),
              patch.object(relay.httpx, "Client", side_effect=lambda *a, **k: self.fresh_clients()),
              contextlib.redirect_stdout(output)):
            self.assertEqual(relay.main(args), 0)

    @staticmethod
    def make_cli_due(path):
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.execute("UPDATE relay_deliveries SET next_attempt_at=? WHERE state='rejected'", (PAST,))
            db.commit()


if __name__ == "__main__":
    unittest.main()
