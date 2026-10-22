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
        self.tenant = {"id": str(TENANT), "role": "owner", "created_at": "2026-10-20T10:00:00Z",
                       "name": "private-tenant-name"}
        self.bot = {"id": str(BOT), "tenant_id": str(TENANT), "is_active": True,
                    "webhook_status": "not_configured", "updated_at": "2026-10-22T10:00:00Z",
                    "token": "private-bot-token", "username": "private-username", "telegram_bot_id": 123456,
                    "name": "private-bot-name"}
        self.tenant_status = self.bot_status = 200
        self.reads = []
        self.fail = set()

        def handle(request):
            self.assertEqual(request.headers["authorization"], "Bearer synthetic-only")
            self.assertEqual(request.headers["x-tenant-id"], str(TENANT))
            if request.method == "GET":
                self.reads.append(str(request.url))
                if request.url.port == 4:
                    self.assertEqual(request.url.path, f"/api/v1/tenants/{TENANT}")
                    return response(self.tenant, self.tenant_status)
                if request.url.port == 5:
                    self.assertEqual(request.url.path, f"/api/v1/tenants/{TENANT}/bots/{BOT}")
                    return response(self.bot, self.bot_status)
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

    def metadata_worker(self):
        return relay.Relay(self.db, self.client, {**ORIGINS, "auth": "http://127.0.0.1:4",
                           "webhook": "http://127.0.0.1:5"}, TENANT, BOT, "synthetic-only")

    def test_all_three_source_types_reach_both_sinks_with_safe_canonical_metadata(self):
        worker = self.metadata_worker()
        self.assertEqual(worker.sweep(), {"pending": 0, "accepted": 6, "unknown": 0})
        events = {body["event_type"]: body for role, body in self.posts if role == "eventpipe"}
        self.assertEqual(set(events), set(relay.SOURCE_TYPES.values()))
        for role, body in self.posts:
            if role == "pipewatch":
                self.assertEqual(body["metadata"], events[body["message"]]["payload"])
        auth = events["auth.tenant.observed"]
        self.assertIsNone(auth["payload"]["bot_id"])
        self.assertNotIn("bot_id", auth["metadata"])
        serialized = json.dumps(list(events.values()))
        for value in ("private-tenant-name", "private-bot-token", "private-username", "private-bot-name", "123456"):
            self.assertNotIn(value, serialized)
        first = self.db.execute("SELECT envelope FROM relay_events ORDER BY id").fetchall()
        self.assertEqual(worker.sweep()["accepted"], 6)
        self.assertEqual(self.db.execute("SELECT envelope FROM relay_events ORDER BY id").fetchall(), first)
        self.assertEqual(len(self.posts), 6)

    def test_inactive_bot_observation_drains_while_denied_ai_pending_work_is_preserved(self):
        worker = self.metadata_worker()
        worker.collect()
        self.source_status = 403
        self.bot = dict(self.bot, is_active=False, webhook_status="failed", updated_at="2026-10-22T10:01:00Z")
        self.assertEqual(worker.sweep(), {"pending": 2, "accepted": 6, "unknown": 0, "source_errors": 1})
        self.assertTrue(all(body.get("event_type", body.get("message")) != relay.EVENT_TYPE for _, body in self.posts))
        failed = [body for role, body in self.posts if role == "pipewatch" and body["metadata"]["payload"].get("webhook_status") == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["level"], "error")
        self.assertFalse(failed[0]["metadata"]["payload"]["is_active"])
        self.source_status = 200
        self.assertEqual(worker.sweep(), {"pending": 0, "accepted": 8, "unknown": 0})

    def test_source_canonical_uuid_and_strict_schema_rejection_blocks_only_its_type(self):
        worker = self.metadata_worker()
        original = self.bot.copy()
        for bad in (dict(original, id=str(uuid4())), dict(original, tenant_id=str(uuid4())),
                    dict(original, is_active=1), dict(original, webhook_status="private-error"),
                    dict(original, updated_at="2026-10-22")):
            self.bot = bad
            self.tenant = dict(self.tenant, id=str(uuid4()))
            counts = worker.sweep()
            self.assertEqual(counts, {"pending": 0, "accepted": 2, "unknown": 0, "source_errors": 2})
        self.assertEqual(len(self.posts), 2)

    def test_auth_source_rejects_mismatched_scope_role_and_invalid_utc_before_any_delivery(self):
        worker = relay.Relay(self.db, self.client, {"auth": "http://127.0.0.1:4",
                            **{key: ORIGINS[key] for key in relay.SINKS}}, TENANT, BOT, "synthetic-only")
        original = self.tenant.copy()
        for bad in (dict(original, id=str(uuid4())), dict(original, role="superadmin"),
                    dict(original, created_at="2026-10-22"),
                    dict(original, created_at="0001-01-01T00:00:00+03:00")):
            self.tenant = bad
            with self.assertRaises(ValueError):
                worker.sweep()
        self.assertEqual(self.posts, [])

    def test_each_saved_source_requires_fresh_authorization_and_all_source_failure_sends_nothing(self):
        worker = self.metadata_worker()
        worker.collect()
        self.source_status = self.bot_status = self.tenant_status = 401
        with self.assertRaises(ValueError):
            worker.sweep()
        self.assertEqual(self.posts, [])
        self.tenant_status = 200
        self.assertEqual(worker.sweep(), {"pending": 4, "accepted": 2, "unknown": 0, "source_errors": 2})
        self.assertTrue(all(body.get("event_type", body.get("message")) == "auth.tenant.observed" for _, body in self.posts))

    def test_auth_identity_ignores_poll_time_and_selected_bot_webhook_identity_uses_utc_state(self):
        item = relay.Tenant.model_validate(self.tenant)
        first = relay.metadata_envelope("auth", item, TENANT, BOT)
        second = relay.metadata_envelope("auth", item, TENANT, uuid4())
        self.assertEqual(first["event_id"], second["event_id"])
        bot = relay.Bot.model_validate(self.bot)
        equivalent = relay.Bot.model_validate(dict(self.bot, updated_at="2026-10-22T13:00:00+03:00"))
        self.assertEqual(relay.metadata_envelope("webhook", bot, TENANT, BOT),
                         relay.metadata_envelope("webhook", equivalent, TENANT, BOT))
        changed = relay.Bot.model_validate(dict(self.bot, is_active=False))
        self.assertNotEqual(relay.metadata_envelope("webhook", bot, TENANT, BOT)["event_id"],
                            relay.metadata_envelope("webhook", changed, TENANT, BOT)["event_id"])

    def test_cli_auth_only_requires_no_agent_and_binds_optional_origins_without_changing_old_state(self):
        path = self.path.parent / "auth.sqlite"
        args = ["--auth-origin", "http://127.0.0.1:4", "--eventpipe-origin", ORIGINS["eventpipe"],
                "--pipewatch-origin", ORIGINS["pipewatch"], "--tenant-id", str(TENANT), "--bot-id", str(BOT), "--state", str(path)]
        with patch.dict(os.environ, {"NEXUS_EVENTS_TOKEN": "synthetic-only"}), patch.object(relay.httpx, "Client", return_value=self.client):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(relay.main(args), 0)
        self.assertEqual(json.loads(output.getvalue()), {"pending": 0, "accepted": 2, "unknown": 0})
        self.assertTrue(all(":4/" in read for read in self.reads))
        with contextlib.closing(sqlite3.connect(path)) as db:
            binding = json.loads(db.execute("SELECT binding FROM relay_meta").fetchone()[0])
        self.assertNotIn("agent", binding["origins"])
        self.assertIn("auth", binding["origins"])
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            relay.open_state(path, "different source identity")
        self.assertEqual(path.read_bytes(), before)

    def test_ai_only_cli_reuses_prior_binding_and_event_identity_without_resending(self):
        event = relay.envelope(relay.Job.model_validate(JOB), TENANT, BOT)
        self.assertEqual(event["event_id"], "b9c7ea7d-f0fb-5b9f-92f1-cd1597d2c24c")
        path = self.path.parent / "prior.sqlite"
        binding = json.dumps({"version": 1, "origins": ORIGINS, "tenant": str(TENANT), "bot": str(BOT)}, sort_keys=True)
        with contextlib.closing(relay.open_state(path, binding)) as db, db:
            relay.Relay(db, self.client, ORIGINS, TENANT, BOT, "synthetic-only").store(event)
            db.execute("UPDATE relay_deliveries SET state='accepted'")
        args = [item for role in ORIGINS for item in (f"--{role}-origin", ORIGINS[role])]
        args += ["--tenant-id", str(TENANT), "--bot-id", str(BOT), "--state", str(path)]
        with patch.dict(os.environ, {"NEXUS_EVENTS_TOKEN": "synthetic-only"}), patch.object(relay.httpx, "Client", return_value=self.client):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(relay.main(args), 0)
        self.assertEqual(json.loads(output.getvalue()), {"pending": 0, "accepted": 2, "unknown": 0})
        self.assertEqual(self.posts, [])

    def test_cli_partial_source_failure_exits_one_and_no_source_fails_before_state_access(self):
        self.bot_status = 503
        args = [item for role in ORIGINS for item in (f"--{role}-origin", ORIGINS[role])]
        args += ["--auth-origin", "http://127.0.0.1:4", "--webhook-origin", "http://127.0.0.1:5",
                 "--tenant-id", str(TENANT), "--bot-id", str(BOT), "--state", str(self.path.parent / "partial.sqlite")]
        with patch.dict(os.environ, {"NEXUS_EVENTS_TOKEN": "synthetic-only"}), patch.object(relay.httpx, "Client", return_value=self.client):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(relay.main(args), 1)
        self.assertEqual(json.loads(output.getvalue()), {"pending": 0, "accepted": 4, "unknown": 0, "source_errors": 1})
        args = [item for role in relay.SINKS for item in (f"--{role}-origin", ORIGINS[role])]
        args += ["--tenant-id", str(TENANT), "--bot-id", str(BOT), "--state", str(self.path)]
        with patch.object(relay, "open_state") as state, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(relay.main(args), 1)
        state.assert_not_called()

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
