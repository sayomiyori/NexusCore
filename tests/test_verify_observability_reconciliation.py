"""Read-only uncertain-delivery reports with real SQLite and HTTP boundaries."""

import contextlib
import copy
import io
import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx

from scripts import relay_observability as relay

TENANT, BOT = UUID(int=10), UUID(int=20)
ORIGINS = {"agent": "http://127.0.0.1:1", "eventpipe": "http://127.0.0.1:2", "pipewatch": "http://127.0.0.1:3"}
QUERY = "http://127.0.0.1:4"
JOB = {"id": str(UUID(int=100)), "event_id": str(UUID(int=200)), "state": "completed",
       "attempts": 1, "updated_at": "2026-10-22T10:00:00Z"}


def response(data, status=200):
    return httpx.Response(status, stream=httpx.ByteStream(json.dumps(data).encode()))


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state # with spaces.sqlite"
        self.binding = json.dumps({"version": 1, "origins": ORIGINS, "tenant": str(TENANT), "bot": str(BOT)}, sort_keys=True)
        self.db = relay.open_state(self.path, self.binding)
        self.addCleanup(self.db.close)
        self.calls, self.records, self.logs = [], [], []
        self.override = lambda request: None

        def handle(request):
            self.assertEqual(request.headers["authorization"], "Bearer synthetic-only")
            self.assertEqual(request.headers["x-tenant-id"], str(TENANT))
            self.calls.append((request.method, str(request.url)))
            override = self.override(request)
            if override is not None:
                return override
            if request.method == "POST":
                body = json.loads(request.content)
                if request.url.port == 2:
                    self.records.append({"event_id": str(uuid4()), "source": body["source"],
                                         "event_type": body["event_type"], "payload": body["payload"], "metadata": body["metadata"]})
                else:
                    self.logs.append(body)
                raise httpx.ReadTimeout("synthetic-lost-receipt-private")
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.content, b"")
            if request.url.port == 1:
                return response({"items": [JOB], "next_cursor": None})
            if request.url.port == 3:
                self.assertEqual(request.url.params["service"], "nexuscore")
                selected = [item for item in self.logs if item["trace_id"] == request.url.params["trace_id"]]
                return response({"total": len(selected), "page": 1, "size": 2, "items": selected[:2]})
            self.assertEqual(request.url.port, 4)
            if request.url.path == "/api/v1/events":
                self.assertEqual(request.url.params["source"], "nexuscore")
                page = int(request.url.params["page"])
                return response([self.summary(item) for item in self.records[(page - 1) * 100:page * 100]])
            return response(next((item for item in self.records if request.url.path.endswith(item["event_id"])),
                {"event_id": request.url.path.rsplit("/", 1)[1], "source": "nexuscore",
                 "event_type": "other", "payload": {}, "metadata": {}}))

        self.handle = handle
        self.client = httpx.Client(transport=httpx.MockTransport(handle), trust_env=False)
        self.addCleanup(self.client.close)
        self.worker = relay.Relay(self.db, self.client, {**ORIGINS, "eventpipe_query": QUERY}, TENANT, BOT, "synthetic-only")
        self.assertEqual(self.worker.sweep(), {"pending": 0, "accepted": 0, "unknown": 2})
        self.calls.clear()

    @staticmethod
    def summary(item):
        return {key: item[key] for key in ("event_id", "source", "event_type")}

    def assert_counts(self, **changes):
        expected = dict.fromkeys(("confirmed", "unresolved", "duplicates", "conflicts", "errors"), 0)
        expected.update(changes)
        self.assertEqual(self.worker.reconcile(), expected)
        self.assertTrue(all(method == "GET" and ":1/" not in url for method, url in self.calls))
        return expected

    def cli(self, extra=None, path=None):
        args = [item for key, value in ORIGINS.items() for item in (f"--{key}-origin", value)]
        args += ["--tenant-id", str(TENANT), "--bot-id", str(BOT), "--state", str(path or self.path), "--reconcile"]
        args += ["--eventpipe-query-origin", QUERY] if extra is None else extra
        stdout, stderr = io.StringIO(), io.StringIO()
        client = httpx.Client(transport=httpx.MockTransport(self.handle), trust_env=False)
        self.addCleanup(client.close)
        with patch.dict(os.environ, {"NEXUS_EVENTS_TOKEN": "synthetic-only"}), \
                patch.object(relay.httpx, "Client", return_value=client), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = relay.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_lost_receipts_confirm_with_gets_only_and_no_sqlite_mutation(self):
        before = self.path.read_bytes()
        with contextlib.closing(relay.open_state(self.path, self.binding, read_only=True)) as db, \
                self.assertRaises(sqlite3.OperationalError):
            db.execute("UPDATE relay_deliveries SET state='accepted'")
        expected = self.assert_counts(confirmed=2)
        self.assert_counts(confirmed=2)
        code, stdout, stderr = self.cli()
        self.assertEqual((code, json.loads(stdout), stderr), (0, expected, ""))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.db.execute("SELECT state FROM relay_deliveries").fetchall(), [("unknown",), ("unknown",)])
        self.assertNotIn("synthetic-only", stdout)
        self.assertNotIn(self.records[0]["event_id"], stdout)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), [self.path.name])

    def test_empty_results_are_unresolved_and_normal_sweep_never_resends(self):
        self.records.clear()
        self.logs.clear()
        self.assert_counts(unresolved=2)
        self.assertEqual(self.worker.sweep()["unknown"], 2)
        self.assertFalse(any(method == "POST" for method, _ in self.calls))

    def test_sink_authorization_and_transport_failures_are_independent(self):
        for status in (401, 403, 404, 429, 500, 302):
            self.override = lambda request, status=status: response({"detail": "private-error"}, status) if request.url.port == 4 else None
            self.assert_counts(confirmed=1, errors=1)
        def unavailable(request):
            if request.url.port == 3:
                raise httpx.ConnectTimeout("private-timeout")
        self.override = unavailable
        self.assert_counts(confirmed=1, errors=1)

    def test_duplicate_copies_and_conflicting_envelopes_never_confirm(self):
        duplicate = copy.deepcopy(self.records[0])
        duplicate["event_id"] = str(uuid4())
        self.records.append(duplicate)
        self.logs.append(copy.deepcopy(self.logs[0]))
        self.assert_counts(duplicates=2)
        self.records[1]["payload"]["payload"]["attempts"] = True
        self.logs[1]["metadata"]["payload"]["attempts"] = True
        self.assert_counts(conflicts=2)

    def test_matching_ids_with_wrong_scope_metadata_or_payload_are_conflicts(self):
        original_record, original_log = copy.deepcopy(self.records[0]), copy.deepcopy(self.logs[0])
        for scope in ("tenant_id", "bot_id", "event_type", "schema_version", "occurred_at"):
            self.records[0] = copy.deepcopy(original_record)
            self.logs[0] = copy.deepcopy(original_log)
            self.records[0]["payload"][scope] = "foreign-private"
            self.logs[0]["metadata"][scope] = "foreign-private"
            self.assert_counts(conflicts=2)
        self.records[0] = copy.deepcopy(original_record)
        self.records[0]["metadata"]["bot_id"] = str(uuid4())
        self.logs[0] = copy.deepcopy(original_log)
        self.logs[0]["message"] = "wrong-type"
        self.assert_counts(conflicts=2)

    def test_foreign_outer_event_type_cannot_hide_a_claimed_relay_identity(self):
        claimed = copy.deepcopy(self.records[0])
        claimed.update(event_id=str(uuid4()), event_type="foreign.type")
        claimed["payload"]["payload"]["attempts"] = 2
        self.records.append(claimed)
        self.assert_counts(confirmed=1, conflicts=1)

    def test_bad_pages_full_details_and_unsafe_storage_ids_fail_closed(self):
        for bad in ({}, None, "private-not-list", [{"event_id": "../private-secret"}]):
            self.override = lambda request, bad=bad: response(bad) if request.url.port == 4 else None
            self.assert_counts(confirmed=1, errors=1)
        self.override = lambda request: response({**self.records[0], "source": "foreign"}) if request.url.path.endswith(self.records[0]["event_id"]) else None
        self.assert_counts(confirmed=1, errors=1)
        self.override = lambda request: response({"total": True, "page": 1, "size": 2, "items": self.logs}) if request.url.port == 3 else None
        self.assert_counts(confirmed=1, errors=1)
        for page in ({"total": 2, "page": 1, "size": 2, "items": self.logs},
                     {"total": 1, "page": True, "size": 2, "items": self.logs},
                     {"total": 1, "page": 1, "size": 2, "items": []}):
            self.override = lambda request, page=page: response(page) if request.url.port == 3 else None
            self.assert_counts(confirmed=1, errors=1)

    def test_late_page_match_and_incomplete_or_repeated_scans(self):
        unrelated = [{"event_id": str(UUID(int=i + 1000)), "source": "nexuscore", "event_type": "other"} for i in range(100)]
        def pages(request):
            if request.url.path == "/api/v1/events":
                return response(unrelated if request.url.params["page"] == "1" else [self.summary(self.records[0])])
        self.override = pages
        self.assert_counts(confirmed=2)
        self.override = lambda request: response(unrelated) if request.url.path == "/api/v1/events" else None
        self.assert_counts(confirmed=1, errors=1)
        def capped(request):
            if request.url.path == "/api/v1/events":
                page = int(request.url.params["page"])
                return response([{**row, "event_id": str(UUID(int=page * 10000 + i))} for i, row in enumerate(unrelated)])
        self.override = capped
        self.assert_counts(confirmed=1, errors=1)
        self.assertTrue(any("page=10&" in url for _, url in self.calls))
        self.override = lambda request: response(self.records and [self.summary(self.records[0])] + unrelated[:99]) if request.url.path == "/api/v1/events" and request.url.params["page"] == "1" else response({}, 503) if request.url.path == "/api/v1/events" else None
        self.assert_counts(confirmed=1, errors=1)

    def test_remote_limits_and_nonfinite_metadata_cannot_confirm(self):
        for raw, headers in ((b"x" * (relay.MAX_BODY + 1), {}), (b"[" * 1100 + b"]" * 1100, {}),
                             (b"{}", {"content-encoding": "gzip"})):
            self.override = lambda request, raw=raw, headers=headers: httpx.Response(200, stream=httpx.ByteStream(raw), headers=headers) if request.url.port == 4 else None
            self.assert_counts(confirmed=1, errors=1)
        self.override = lambda request: response({"total": 1, "page": 1, "size": 2,
            "items": [{**self.logs[0], "metadata": {"bad": float("nan")}}]}) if request.url.port == 3 else None
        self.assert_counts(confirmed=1, errors=1)

    def test_invalid_local_state_rejected_before_http_with_static_cli_failure(self):
        event = json.loads(self.db.execute("SELECT envelope FROM relay_events").fetchone()[0])
        for bad in (dict(event, tenant_id=str(uuid4())), dict(event, bot_id=str(uuid4())), dict(event, schema_version=True),
                    dict(event, private="private-sentinel"), dict(event, occurred_at="2026-10-22")):
            with self.db:
                self.db.execute("UPDATE relay_events SET envelope=?", (json.dumps(bad),))
            with self.assertRaises(ValueError):
                self.worker.reconcile()
        self.assertEqual(self.calls, [])
        with self.db:
            self.db.execute("UPDATE relay_events SET envelope=?", ("[" * 1100 + "]" * 1100,))
        before = self.path.read_bytes()
        code, stdout, stderr = self.cli()
        self.assertEqual((code, stdout), (1, ""))
        self.assertEqual(stderr, "Relay failed; input, credentials, response and filesystem details withheld\n")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.calls, [])

    def test_missing_state_binding_mismatch_and_invalid_options_before_network(self):
        missing = self.path.parent / "absent.sqlite"
        for extra in ([], ["--eventpipe-query-origin", QUERY, "--interval", "5"],
                      ["--eventpipe-query-origin", "https://public.example/private-secret"]):
            code, stdout, _ = self.cli(extra, missing)
            self.assertEqual((code, stdout), (1, ""))
            self.assertFalse(missing.exists())
        self.assertEqual(self.cli(path=missing)[:2], (1, ""))
        self.assertFalse(missing.exists())
        with self.assertRaises(ValueError):
            relay.open_state(self.path, "foreign-binding", read_only=True)
        with self.assertRaises(ValueError):
            relay.open_state(self.path.parent, self.binding, read_only=True)
        self.assertEqual(self.calls, [])

    def test_unknown_row_limit_rejects_before_queries(self):
        with self.db:
            for i in range(101):
                self.db.execute("INSERT INTO relay_deliveries VALUES (?,'eventpipe','unknown',NULL)", (str(UUID(int=i + 999)),))
        with self.assertRaises(ValueError):
            self.worker.reconcile()
        self.assertEqual(self.calls, [])

    def test_orphan_unknown_row_is_not_silently_ignored(self):
        with self.db:
            self.db.execute("INSERT INTO relay_deliveries VALUES (?,'eventpipe','unknown',NULL)", (str(uuid4()),))
        before = self.path.read_bytes()
        code, stdout, stderr = self.cli()
        self.assertEqual((code, stdout), (1, ""))
        self.assertEqual(stderr, "Relay failed; input, credentials, response and filesystem details withheld\n")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.calls, [])

    def test_query_origin_without_reconciliation_fails_before_state_or_http(self):
        args = [item for key, value in ORIGINS.items() for item in (f"--{key}-origin", value)]
        args += ["--tenant-id", str(TENANT), "--bot-id", str(BOT), "--state", str(self.path),
                 "--eventpipe-query-origin", QUERY]
        with patch.object(relay, "open_state") as state, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(relay.main(args), 1)
        state.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_empty_and_concurrent_reports_do_not_change_state(self):
        before = self.path.read_bytes()
        def check(_):
            with contextlib.closing(relay.open_state(self.path, self.binding, read_only=True)) as db:
                return relay.Relay(db, self.client, self.worker.origins, TENANT, BOT, "synthetic-only").reconcile()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(check, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["confirmed"], 2)
        self.assertEqual(self.path.read_bytes(), before)
        with self.db:
            self.db.execute("UPDATE relay_deliveries SET state='accepted'")
        self.calls.clear()
        self.assert_counts()
        self.assertEqual(self.calls, [])

    def test_wal_state_and_links_rejected_without_creating_sqlite_sidecars(self):
        wal_path = self.path.parent / "wal.sqlite"
        with contextlib.closing(relay.open_state(wal_path, self.binding)) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone(), ("wal",))
        before = {p.name: p.read_bytes() for p in self.path.parent.iterdir()}
        with self.assertRaises(ValueError):
            relay.open_state(wal_path, self.binding, read_only=True)
        self.assertEqual({p.name: p.read_bytes() for p in self.path.parent.iterdir()}, before)
        link = self.path.parent / "state-link.sqlite"
        try:
            link.symlink_to(self.path)
        except OSError:
            self.skipTest("File symlink privilege unavailable")
        with self.assertRaises(ValueError):
            relay.open_state(link, self.binding, read_only=True)

    def test_all_three_saved_types_validate_and_auth_null_bot_survives(self):
        events = [relay.metadata_envelope("auth", relay.Tenant(id=TENANT, role="owner", created_at="2026-10-21T10:00:00Z"), TENANT, BOT),
                  relay.metadata_envelope("webhook", relay.Bot(id=BOT, tenant_id=TENANT, is_active=False,
                     webhook_status="failed", updated_at="2026-10-23T10:00:00Z"), TENANT, BOT)]
        with self.db:
            for event in events:
                self.worker.store(event)
                self.records.append({"event_id": str(uuid4()), "source": "nexuscore", "event_type": event["event_type"],
                    "payload": event, "metadata": {"relay_event_id": event["event_id"], **({"bot_id": event["bot_id"]} if event["bot_id"] else {})}})
                self.logs.append({"service": "nexuscore", "message": event["event_type"], "trace_id": event["event_id"], "metadata": event})
            self.db.execute("UPDATE relay_deliveries SET state='unknown'")
        self.assert_counts(confirmed=6)


if __name__ == "__main__":
    unittest.main()
