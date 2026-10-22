"""Root relay contracts with real SQLite state and controlled HTTP boundaries."""

import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx

from scripts import relay_observability as relay

TENANT, BOT = UUID(int=10), UUID(int=20)
ORIGINS = {"agent": "http://127.0.0.1:1", "eventpipe": "http://127.0.0.1:2", "pipewatch": "http://127.0.0.1:3"}
JOB = {"id": str(UUID(int=100)), "event_id": str(UUID(int=200)), "state": "completed",
       "attempts": 1, "updated_at": "2026-10-22T10:00:00Z", "provider": "private-provider",
       "model": "private-model", "question": "private-message", "token": "private-token"}


def response(data, status=200, headers=None):
    return httpx.Response(status, stream=httpx.ByteStream(json.dumps(data).encode()), headers=headers)


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.sqlite"
        self.db = relay.open_state(self.path, "binding")
        self.addCleanup(self.db.close)
        self.posts = []
        self.page = {"items": [JOB], "next_cursor": None}
        self.source_status = 200
        self.fail = set()

        def handle(request):
            self.assertEqual(request.headers["authorization"], "Bearer synthetic-only")
            self.assertEqual(request.headers["x-tenant-id"], str(TENANT))
            if request.method == "GET":
                return response(self.page, self.source_status)
            role = "eventpipe" if request.url.port == 2 else "pipewatch"
            self.assertEqual(request.url.path, "/api/v1/events" if role == "eventpipe" else "/api/v1/logs")
            self.posts.append((role, json.loads(request.content)))
            if role in self.fail:
                raise httpx.ReadTimeout("private-transport-details")
            return response({"status": "accepted", "event_id": str(uuid4())} if role == "eventpipe"
                            else {"status": "accepted", "count": 1})

        self.handle = handle
        self.client = httpx.Client(transport=httpx.MockTransport(handle), trust_env=False)
        self.addCleanup(self.client.close)
        self.worker = relay.Relay(self.db, self.client, ORIGINS, TENANT, BOT, "synthetic-only")

    def test_same_safe_envelope_reaches_both_sinks_once_and_state_survives_reopen(self):
        self.assertEqual(self.worker.sweep(), {"pending": 0, "accepted": 2, "unknown": 0})
        event = self.posts[0][1]["payload"]
        self.assertEqual(event, self.posts[1][1]["metadata"])
        self.assertEqual(self.posts[1][1]["trace_id"], event["event_id"])
        self.assertEqual(event["tenant_id"], str(TENANT))
        self.assertEqual(event["bot_id"], str(BOT))
        for secret in ("private-token", "private-model", "private-provider", "private-message", "synthetic-only"):
            self.assertNotIn(secret, json.dumps(event))
            self.assertNotIn(secret.encode(), self.path.read_bytes())
        with contextlib.closing(relay.open_state(self.path, "binding")) as db:
            other = relay.Relay(db, self.client, ORIGINS, TENANT, BOT, "synthetic-only")
            self.assertEqual(other.sweep()["accepted"], 2)
        self.assertEqual(len(self.posts), 2)

    def test_partial_sink_timeout_is_unknown_other_sink_succeeds_and_no_automatic_resend(self):
        self.fail.add("eventpipe")
        self.assertEqual(self.worker.sweep(), {"pending": 0, "accepted": 1, "unknown": 1})
        self.fail.clear()
        self.assertEqual(self.worker.sweep()["unknown"], 1)
        self.assertEqual(len(self.posts), 2)

    def test_pending_work_resumes_when_source_state_disappears_but_not_after_source_denial(self):
        self.worker.collect()
        self.page = {"items": [], "next_cursor": None}
        for status in (401, 403, 404, 503):
            self.source_status = status
            with self.assertRaises(ValueError):
                self.worker.sweep()
            self.assertEqual(self.posts, [])
        self.source_status = 200
        self.assertEqual(self.worker.sweep()["accepted"], 2)

    def test_crash_after_claim_never_resends_unknown_and_other_pending_sink_recovers(self):
        self.worker.collect()
        with self.db:
            self.db.execute("UPDATE relay_deliveries SET state='unknown' WHERE sink='eventpipe'")
        self.assertEqual(self.worker.sweep(), {"pending": 0, "accepted": 1, "unknown": 1})
        self.assertEqual([x[0] for x in self.posts], ["pipewatch"])

    def test_changed_job_state_produces_new_event_and_equivalent_utc_offsets_do_not(self):
        self.worker.sweep()
        self.page["items"] = [dict(JOB, updated_at="2026-10-22T13:00:00+03:00")]
        self.worker.sweep()
        self.assertEqual(len(self.posts), 2)
        self.page["items"] = [dict(JOB, state="failed")]
        self.worker.sweep()
        self.assertEqual(len(self.posts), 4)
        self.assertEqual(self.posts[-1][1]["level"], "error")

    def test_pagination_scans_from_start_and_validates_order_schema_and_bounds(self):
        first = {"items": [JOB], "next_cursor": JOB["id"]}
        second = {"items": [dict(JOB, id=str(UUID(int=101)))], "next_cursor": None}
        reads = []

        def handle(request):
            if request.method == "GET":
                reads.append(request.url.params.get("cursor"))
                return response(second if reads[-1] else first)
            return self.handle(request)

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            worker = relay.Relay(self.db, client, ORIGINS, TENANT, BOT, "synthetic-only")
            self.assertEqual(worker.sweep()["accepted"], 4)
            worker.sweep()
        self.assertEqual(reads, [None, JOB["id"], None, JOB["id"]])
        for page in ({"items": [JOB], "next_cursor": str(UUID(int=1))},
                     {"items": [JOB, JOB], "next_cursor": None},
                     {"items": [dict(JOB, attempts=True)], "next_cursor": None},
                     {"items": [dict(JOB, state="private-error")], "next_cursor": None},
                     {"items": [dict(JOB, updated_at="2026-10-22")], "next_cursor": None},
                     {"items": [dict(JOB, updated_at="0001-01-01T00:00:00+03:00")], "next_cursor": None},
                     {"items": [dict(JOB, updated_at="9999-12-31T23:59:59-03:00")], "next_cursor": None},
                     {"items": [JOB] * 101, "next_cursor": None}):
            self.page = page
            with self.assertRaises(ValueError):
                self.worker.collect()

    def test_concurrent_process_connections_claim_each_sink_once(self):
        self.worker.collect()
        barrier = threading.Barrier(2)

        def invoke(_):
            with contextlib.closing(relay.open_state(self.path, "binding")) as db:
                barrier.wait(timeout=5)
                return relay.Relay(db, self.client, ORIGINS, TENANT, BOT, "synthetic-only").sweep()

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(invoke, range(2)))
        self.assertEqual(sorted(x[0] for x in self.posts), ["eventpipe", "pipewatch"])

    def test_page_limit_is_explicit_and_never_drains_a_partial_scan(self):
        reads = []
        def handle(request):
            self.assertEqual(request.method, "GET")
            reads.append(request)
            job = dict(JOB, id=str(UUID(int=1000 + len(reads))))
            return response({"items": [job], "next_cursor": job["id"]})
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            worker = relay.Relay(self.db, client, ORIGINS, TENANT, BOT, "synthetic-only")
            with self.assertRaises(ValueError):
                worker.sweep()
        self.assertEqual(len(reads), 100)
        self.assertEqual(self.db.execute("SELECT count(*) FROM relay_deliveries WHERE state='pending'").fetchone()[0], 200)

    def test_receipt_validation_and_response_limits_fail_closed_without_raw_diagnostics(self):
        for result in (lambda: response({}, 302), lambda: response({}, 401), lambda: response({}, 503),
                       lambda: response({"x": "a" * relay.MAX_BODY}),
                       lambda: response({}, headers={"content-encoding": "gzip"}),
                       lambda: httpx.Response(200, stream=httpx.ByteStream(b"not json")),
                       lambda: httpx.Response(200, stream=httpx.ByteStream(b"[" * 3000 + b"0" + b"]" * 3000))):
            with httpx.Client(transport=httpx.MockTransport(lambda _, factory=result: factory())) as client:
                worker = relay.Relay(self.db, client, ORIGINS, TENANT, BOT, "synthetic-only")
                with self.assertRaises(ValueError):
                    worker.collect()
        for bad in ({}, {"status": "accepted", "count": True}, {"status": "accepted", "event_id": "private-invalid"}):
            with self.db:
                self.db.execute("DELETE FROM relay_deliveries")
                self.db.execute("DELETE FROM relay_events")
            def handle(request, bad=bad):
                return self.handle(request) if request.method == "GET" else response(bad)
            with httpx.Client(transport=httpx.MockTransport(handle)) as client:
                worker = relay.Relay(self.db, client, ORIGINS, TENANT, BOT, "synthetic-only")
                self.assertEqual(worker.sweep()["unknown"], 2)

    def test_state_binding_rejection_preserves_original_and_rejects_foreign_files(self):
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            relay.open_state(self.path, "different")
        self.assertEqual(self.path.read_bytes(), before)
        other = self.path.parent / "foreign.sqlite"
        with contextlib.closing(sqlite3.connect(other)) as db:
            db.execute("CREATE TABLE user_data(value TEXT)")
        before = other.read_bytes()
        with self.assertRaises(sqlite3.Error):
            relay.open_state(other, "binding")
        self.assertEqual(other.read_bytes(), before)
        link = self.path.parent / "link.sqlite"
        try:
            link.symlink_to(self.path)
        except OSError:
            return
        with self.assertRaises(ValueError):
            relay.open_state(link, "binding")

    def test_origin_validation_requires_explicit_numeric_private_origins(self):
        for value in ("http://127.0.0.1:8000", "https://10.1.2.3", "http://172.16.1.2", "http://192.168.1.2"):
            self.assertTrue(relay.origin(value))
        for value in ("http://example.com", "http://169.254.169.254", "http://8.8.8.8", "http://0.0.0.0",
                      "http://[::1]", "http://127.0.0.1:0", "http://127.0.0.1/path", "http://x@127.0.0.1",
                      "http://127.0.0.1?x=y", "http://127.0.0.1#x", "http://127.0.0.1:", " http://127.0.0.1"):
            with self.assertRaises(ValueError, msg=value):
                relay.origin(value)

    def test_cli_invalid_arguments_and_failures_hide_secrets_before_state_or_transport(self):
        sentinel = "private-credential-sentinel"
        result = subprocess.run([sys.executable, "-B", "scripts/relay_observability.py", "--" + sentinel],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(sentinel, result.stdout + result.stderr)
        args = [item for role in ORIGINS for item in (f"--{role}-origin", ORIGINS[role])]
        args += ["--tenant-id", str(TENANT), "--bot-id", str(BOT), "--state", str(self.path)]
        with patch.dict(os.environ, {"NEXUS_EVENTS_TOKEN": sentinel + "\n"}), patch.object(relay, "open_state") as state:
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                self.assertEqual(relay.main(args), 1)
            state.assert_not_called()
            self.assertNotIn(sentinel, output.getvalue())

    def test_cli_transport_failure_has_static_diagnostic_without_response_or_token(self):
        sentinel = "private-error-sentinel"
        def fail(_):
            raise httpx.ConnectError(sentinel)
        args = [item for role in ORIGINS for item in (f"--{role}-origin", ORIGINS[role])]
        args += ["--tenant-id", str(TENANT), "--bot-id", str(BOT), "--state", str(self.path.parent / 'cli.sqlite')]
        with (contextlib.closing(httpx.Client(transport=httpx.MockTransport(fail))) as client,
              patch.dict(os.environ, {"NEXUS_EVENTS_TOKEN": sentinel}),
              patch.object(relay.httpx, "Client", return_value=client)):
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(relay.main(args), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn(sentinel, errors.getvalue())
        self.assertIn("details withheld", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
