"""Relay tenant-authorized metadata observations to EventPipe and PipeWatch; opt-in only."""

import argparse
import ipaddress
import json
import os
import sqlite3
import stat
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from pydantic import AwareDatetime, BaseModel, Field, StrictBool

if __package__:
    from .local_files import new_descriptor
else:
    from local_files import new_descriptor

MAX_BODY = 256 * 1024
SINKS = ("eventpipe", "pipewatch")
EVENT_TYPE = "ai.job.observed"
SOURCE_TYPES = {"agent": EVENT_TYPE, "auth": "auth.tenant.observed", "webhook": "webhook.bot.observed"}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        super().error("Invalid arguments; details withheld")


class Job(BaseModel):
    id: UUID
    event_id: UUID
    state: Literal["pending", "processing", "completed", "failed", "unknown"]
    attempts: int = Field(strict=True, ge=0, le=2**31 - 1)
    updated_at: AwareDatetime


class Page(BaseModel):
    items: list[Job] = Field(max_length=100)
    next_cursor: UUID | None


class Tenant(BaseModel):
    id: UUID
    role: Literal["owner", "member"]
    created_at: AwareDatetime


class Bot(BaseModel):
    id: UUID
    tenant_id: UUID
    is_active: StrictBool
    webhook_status: Literal["not_configured", "configuring", "configured", "failed", "unknown"]
    updated_at: AwareDatetime


def origin(value):
    parsed = urlsplit(value)
    address = ipaddress.IPv4Address(parsed.hostname or "")
    allowed = any(address in ipaddress.IPv4Network(net) for net in (
        "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    ))
    if (not allowed or parsed.scheme not in {"http", "https"} or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"} or parsed.port == 0 or parsed.netloc.endswith(":")
            or not value.isascii() or any(c.isspace() or ord(c) < 32 for c in value)):
        raise ValueError("Invalid private origin")
    return f"{parsed.scheme}://{address}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"


def open_state(path, binding):
    if path.is_symlink() or path.is_junction() or (path.exists() and not stat.S_ISREG(path.stat().st_mode)):
        raise ValueError("Invalid state file")
    fresh = not path.exists()
    if fresh:
        os.close(new_descriptor(path))
    db = sqlite3.connect(path, timeout=5)
    try:
        if fresh:
            db.executescript("""
                CREATE TABLE relay_meta(binding TEXT NOT NULL);
                CREATE TABLE relay_events(id TEXT PRIMARY KEY, envelope TEXT NOT NULL);
                CREATE TABLE relay_deliveries(
                    event_id TEXT NOT NULL REFERENCES relay_events(id), sink TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','unknown','accepted')),
                    receipt TEXT, PRIMARY KEY(event_id,sink));
            """)
            with db:
                db.execute("INSERT INTO relay_meta VALUES (?)", (binding,))
        if db.execute("SELECT binding FROM relay_meta").fetchall() != [(binding,)]:
            raise ValueError("State identity mismatch")
        return db
    except Exception:
        db.close()
        raise


def utc_timestamp(value):
    try:
        return value.astimezone(UTC).isoformat()
    except OverflowError:
        raise ValueError("Timestamp exceeds UTC range") from None


def envelope(job, tenant_id, bot_id):
    occurred = utc_timestamp(job.updated_at)
    identifier = str(uuid5(NAMESPACE_URL, json.dumps([
        EVENT_TYPE, str(tenant_id), str(bot_id), str(job.id), str(job.event_id),
        job.state, job.attempts, occurred,
    ], separators=(",", ":"))))
    return {"event_id": identifier, "event_type": EVENT_TYPE, "schema_version": 1,
            "occurred_at": occurred, "tenant_id": str(tenant_id), "bot_id": str(bot_id),
            "correlation_id": str(job.event_id), "idempotency_key": identifier,
            "payload": {"job_id": str(job.id), "ingress_event_id": str(job.event_id),
                        "state": job.state, "attempts": job.attempts}}


def metadata_envelope(role, item, tenant_id, bot_id):
    kind = SOURCE_TYPES[role]
    if role == "auth":
        if item.id != tenant_id:
            raise ValueError("Canonical tenant mismatch")
        scope_bot = None
        payload = {"tenant_created_at": utc_timestamp(item.created_at), "observed_role": item.role}
        occurred = utc_timestamp(datetime.now(UTC))
        identity_time = None
    else:
        if item.id != bot_id or item.tenant_id != tenant_id:
            raise ValueError("Canonical bot scope mismatch")
        scope_bot = str(bot_id)
        payload = {"is_active": item.is_active, "webhook_status": item.webhook_status}
        occurred = identity_time = utc_timestamp(item.updated_at)
    identifier = str(uuid5(NAMESPACE_URL, json.dumps([
        kind, str(tenant_id), scope_bot, identity_time, payload,
    ], sort_keys=True, separators=(",", ":"))))
    return {"event_id": identifier, "event_type": kind, "schema_version": 1,
            "occurred_at": occurred, "tenant_id": str(tenant_id), "bot_id": scope_bot,
            "correlation_id": str(item.id), "idempotency_key": identifier, "payload": payload}


class Relay:
    def __init__(self, db, client, origins, tenant_id, bot_id, token):
        self.db, self.client, self.origins = db, client, origins
        self.tenant_id, self.bot_id = tenant_id, bot_id
        if not 1 <= len(token) <= 8192 or not token.isascii() or any(c.isspace() or ord(c) < 32 for c in token):
            raise ValueError("Invalid bearer")
        self.headers = {"Authorization": "Bearer " + token, "X-Tenant-ID": str(tenant_id),
                        "Accept-Encoding": "identity"}

    def request(self, method, role, path, body=None):
        with self.client.stream(method, self.origins[role] + path, headers=self.headers, json=body,
                                follow_redirects=False) as response:
            if response.status_code != 200 or response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("Unexpected response")
            raw = bytearray()
            for chunk in response.iter_raw():
                if len(raw) + len(chunk) > MAX_BODY:
                    raise ValueError("Response too large")
                raw.extend(chunk)
            try:
                return json.loads(raw)
            except RecursionError:
                raise ValueError("Nested response exceeds parser limit") from None

    def store(self, event):
        encoded = json.dumps(event, sort_keys=True, separators=(",", ":"))
        self.db.execute("INSERT OR IGNORE INTO relay_events VALUES (?,?)", (event["event_id"], encoded))
        for sink in SINKS:
            self.db.execute("INSERT OR IGNORE INTO relay_deliveries VALUES (?,?,'pending',NULL)", (event["event_id"], sink))

    def collect_jobs(self):
        cursor = None
        route = f"/api/v1/tenants/{self.tenant_id}/bots/{self.bot_id}/ai/jobs?limit=100"
        for _ in range(100):
            page = Page.model_validate(self.request("GET", "agent", route + (f"&cursor={cursor}" if cursor else "")))
            if page.next_cursor and (not page.items or page.next_cursor != page.items[-1].id
                                     or (cursor is not None and page.next_cursor <= cursor)):
                raise ValueError("Invalid pagination")
            if any(a.id >= b.id for a, b in zip(page.items, page.items[1:])) or (
                    cursor is not None and any(item.id <= cursor for item in page.items)):
                raise ValueError("Unordered page")
            with self.db:
                for job in page.items:
                    self.store(envelope(job, self.tenant_id, self.bot_id))
            if page.next_cursor is None:
                return
            cursor = page.next_cursor
        raise ValueError("Sweep page limit exceeded")

    def collect(self):
        allowed = set()
        failures = 0
        for role, kind in SOURCE_TYPES.items():
            if role not in self.origins:
                continue
            try:
                if role == "agent":
                    self.collect_jobs()
                else:
                    route = f"/api/v1/tenants/{self.tenant_id}"
                    if role == "webhook":
                        route += f"/bots/{self.bot_id}"
                    model = Tenant if role == "auth" else Bot
                    item = model.model_validate(self.request("GET", role, route))
                    event = metadata_envelope(role, item, self.tenant_id, self.bot_id)
                    with self.db:
                        self.store(event)
                allowed.add(kind)
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                failures += 1
        if not allowed:
            raise ValueError("No source completed an authorized scan")
        return allowed, failures

    def sweep(self):
        # Gate each type on its own fresh source authorization, including saved pending rows.
        allowed, failures = self.collect()
        pending = self.db.execute("SELECT event_id,sink FROM relay_deliveries WHERE state='pending'").fetchall()
        for identifier, sink in pending:
            event = json.loads(self.db.execute("SELECT envelope FROM relay_events WHERE id=?", (identifier,)).fetchone()[0])
            if event["event_type"] not in allowed:
                continue
            with self.db:
                claimed = self.db.execute("UPDATE relay_deliveries SET state='unknown' "
                                          "WHERE event_id=? AND sink=? AND state='pending'", (identifier, sink)).rowcount
            if not claimed:
                continue
            try:
                if sink == "eventpipe":
                    receipt = self.request("POST", sink, "/api/v1/events", {
                        "source": "nexuscore", "event_type": event["event_type"], "payload": event,
                        "metadata": {"relay_event_id": identifier, **({"bot_id": event["bot_id"]} if event["bot_id"] else {})},
                    })
                    if receipt.get("status") != "accepted":
                        raise ValueError("Invalid receipt")
                    remote_id = str(UUID(receipt["event_id"]))
                else:
                    receipt = self.request("POST", sink, "/api/v1/logs", {
                        "service": "nexuscore", "level": "error" if any(
                            event["payload"].get(key) in {"failed", "unknown"} for key in ("state", "webhook_status")) else "info",
                        "message": event["event_type"], "trace_id": identifier, "metadata": event,
                    })
                    if receipt != {"status": "accepted", "count": 1} or type(receipt["count"]) is not int:
                        raise ValueError("Invalid receipt")
                    remote_id = None
                with self.db:
                    self.db.execute("UPDATE relay_deliveries SET state='accepted',receipt=? WHERE event_id=? AND sink=?",
                                    (remote_id, identifier, sink))
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                # Either sink may have committed before losing its response; never resend automatically.
                continue
        counts = dict(self.db.execute("SELECT state,count(*) FROM relay_deliveries GROUP BY state").fetchall())
        return {**{state: counts.get(state, 0) for state in ("pending", "accepted", "unknown")},
                **({"source_errors": failures} if failures else {})}


def main(argv=None):
    parser = Parser(description=__doc__)
    for role in SINKS:
        parser.add_argument(f"--{role}-origin", required=True)
    for role in SOURCE_TYPES:
        parser.add_argument(f"--{role}-origin")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--interval", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        origins = {role: origin(getattr(args, role + "_origin")) for role in (*SOURCE_TYPES, *SINKS)
                   if getattr(args, role + "_origin") is not None}
        if not set(SOURCE_TYPES) & origins.keys():
            raise ValueError("At least one source is required")
        if args.interval != 0 and not 5 <= args.interval <= 3600:
            raise ValueError("Invalid relay configuration")
        tenant_id, bot_id = UUID(args.tenant_id), UUID(args.bot_id)
        token = os.environ.get("NEXUS_EVENTS_TOKEN", "")
        if not token or not token.isascii() or not token.isprintable() or any(c.isspace() for c in token) or len(token) > 8192:
            raise ValueError("Invalid bearer")
        binding = json.dumps({"version": 1, "origins": origins, "tenant": str(tenant_id), "bot": str(bot_id)}, sort_keys=True)
        with closing(open_state(args.state, binding)) as db, httpx.Client(
                timeout=httpx.Timeout(5, connect=2), trust_env=False, follow_redirects=False) as client:
            relay = Relay(db, client, origins, tenant_id, bot_id, token)
            while True:
                counts = relay.sweep()
                print(json.dumps(counts), flush=True)
                if counts["pending"] or counts["unknown"] or counts.get("source_errors"):
                    return 1
                if not args.interval:
                    return 0
                time.sleep(args.interval)
    except (OSError, ValueError, sqlite3.Error, httpx.HTTPError, TypeError, KeyError, AttributeError):
        print("Relay failed; input, credentials, response and filesystem details withheld", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
