"""Verify the built Telegram/AI/reply chain in a fresh owned internal fixture.

No external test database, published ports, root credentials or live calls.
Only synthetic Telegram/Groq HTTP effects are intercepted; storage, issuer,
queues, workers and recovery scans use the actual service implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import secrets
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from cryptography.fernet import Fernet

if __package__:
    from . import verify_stack as smoke
else:
    import verify_stack as smoke

TOKEN = "123456:synthetic_VERIFICATION-send-token"
WORKERS = ("webhook_worker", "agent_worker", "agent_publisher", "webhook_sender")


def controlled_origin():
    value = os.environ["CONTROLLED_PROVIDER_URL"]
    parsed = urlsplit(value)
    address = ipaddress.IPv4Address(parsed.hostname or "")
    smoke.require(parsed.scheme == "http" and parsed.port == 8000 and address.is_private
                  and not address.is_loopback and not address.is_link_local
                  and not address.is_unspecified and not address.is_multicast
                  and not parsed.username and not parsed.password and not parsed.path
                  and not parsed.query and not parsed.fragment, "Unsafe controlled provider origin")
    return value


def internal_request(request):
    smoke.require(request.url.scheme == "http" and request.url.host in {
        "auth_service", "webhook_service", "agent_service"} and request.url.port == 8000
        and not request.url.userinfo, "Unexpected controlled HTTP destination")


def create_webhook_app():
    """Intercept synthetic Telegram setup; retain real issuer and storage."""
    from src.api.main import app
    from src.api.v1.dependencies.platform import get_telegram
    from src.infrastructure.platform.clients import TelegramClient

    def boundary(request):
        method = request.url.path.rsplit("/", 1)[-1]
        smoke.require(str(request.url) == f"https://api.telegram.org/bot{TOKEN}/{method}"
                      and method in {"getMe", "setWebhook"}, "Non-synthetic Telegram setup refused")
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
            response = client.post(controlled_origin() + "/controlled/" + method,
                                   json=json.loads(request.content) if request.content else {})
        return httpx.Response(response.status_code, json=response.json())

    app.dependency_overrides[get_telegram] = lambda: TelegramClient(transport=httpx.MockTransport(boundary))
    return app


def install_worker_boundary():
    """Intercept only provider effects and one deliberately lost admission receipt."""
    original = httpx.AsyncClient
    lost_receipt = False

    async def boundary(request):
        nonlocal lost_receipt
        role = os.environ["VERIFICATION_ROLE"]
        target = None
        if request.url.host == "api.groq.com":
            smoke.require(role == "generator" and str(request.url) ==
                          "https://api.groq.com/openai/v1/chat/completions" and
                          request.headers["Authorization"] == "Bearer synthetic-groq-verification",
                          "Non-synthetic Groq request refused")
            target = "/groq"
        elif request.url.host == "api.telegram.org":
            smoke.require(role == "sender" and str(request.url) ==
                          f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                          "Non-synthetic Telegram send refused")
            target = "/send"
        if target:
            async with original(timeout=20, trust_env=False, follow_redirects=False) as client:
                return await client.post(controlled_origin() + target, content=request.content,
                                         headers={"Content-Type": "application/json"})
        internal_request(request)
        async with original(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = await client.send(request)
        if role == "ingress" and request.url.path == "/internal/v1/telegram/updates" and response.status_code == 202 and not lost_receipt:
            lost_receipt = True
            async with original(timeout=5, trust_env=False, follow_redirects=False) as client:
                await client.post(controlled_origin() + "/lost-receipt", json={})
            return httpx.Response(503)
        return response

    class ControlledClient(original):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(boundary)
            super().__init__(**kwargs)

    httpx.AsyncClient = ControlledClient


def receiver_handler():
    records = {"setup": [], "groq": 0, "send": 0, "lost_receipts": 0, "errors": 0}
    lock = threading.Lock()

    class Receiver(BaseHTTPRequestHandler):
        def respond(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                self.respond(200, {"status": "ok"})
            elif self.path == "/receipt":
                with lock:
                    self.respond(200, records)
            else:
                self.respond(404, {})

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                smoke.require(0 < size <= 65536, "Invalid controlled request size")
                payload = json.loads(self.rfile.read(size))
                with lock:
                    if self.path == "/controlled/getMe":
                        reply = {"ok": True, "result": {"id": 123456, "is_bot": True, "username": "controlled_bot"}}
                    elif self.path == "/controlled/setWebhook":
                        records["setup"].append(payload)
                        reply = {"ok": True, "result": True}
                    elif self.path == "/lost-receipt":
                        records["lost_receipts"] += 1
                        reply = {}
                    elif self.path == "/groq":
                        smoke.require(payload["model"] == "openai/gpt-oss-20b" and
                                      payload["max_completion_tokens"] == 1024 and "tools" not in payload and
                                      payload["messages"][-1] == {"role": "user", "content": "Synthetic question"},
                                      "Unexpected controlled generation")
                        records["groq"] += 1
                        reply = {"id": "synthetic", "object": "chat.completion", "created": 1,
                                 "model": payload["model"], "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": "Synthetic sender answer"}}],
                                 "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
                    elif self.path == "/send":
                        smoke.require(payload == {"chat_id": 17, "text": "Synthetic sender answer"}, "Unexpected canonical send")
                        from sqlalchemy import create_engine, text
                        engine = create_engine(os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg"))
                        try:
                            with engine.connect() as connection:
                                state = connection.execute(text("SELECT state,send_started_at FROM telegram_answers")).one()
                                smoke.require(state[0] == "processing" and state[1] is not None, "Send marker not committed before effect")
                        finally:
                            engine.dispose()
                        records["send"] += 1
                        reply = {"ok": True, "result": {"message_id": 717, "chat": {"id": 17}}}
                    else:
                        raise smoke.VerificationError("Unexpected controlled route")
                self.respond(200, reply)
            except Exception:  # noqa: BLE001 - Receiver errors must not disclose test credentials.
                with lock:
                    records["errors"] += 1
                self.respond(400, {})

        def log_message(self, *_):
            pass

    return Receiver


def ai_config(images, scanners=False):
    config = smoke.smoke_config(images)
    services = config["services"]
    # Preserve issuer sessions when deliberately restarting the fixture broker.
    services["redis"]["command"] = ["redis-server", "--save", "", "--appendonly", "yes", "--appendfsync", "always"]
    auth = services["auth_service"]["environment"]
    auth.update(dict.fromkeys(smoke.EXTERNAL, ""), AUTHFORTRESS_WEBHOOK_SERVICE_KEY="${AI_SERVICE_KEY}")
    web = {**services["webhook_service"]["environment"], "PLATFORM_BOTS_ENABLED": "true",
           "PLATFORM_TELEGRAM_ENABLED": "true", "TELEGRAM_REPLIES_ENABLED": "true",
           "AUTHFORTRESS_BASE_URL": "http://auth_service:8000", "AGENTHUB_BASE_URL": "http://agent_service:8000",
           "AUTHFORTRESS_WEBHOOK_SERVICE_KEY": "${AI_SERVICE_KEY}", "WEBHOOK_AGENT_CONTEXT_KEY": "${AI_CONTEXT_KEY}",
           "WEBHOOK_AGENT_INGRESS_KEY": "${AI_INGRESS_KEY}", "AGENT_WEBHOOK_REPLY_KEY": "${AI_REPLY_KEY}",
           "BOT_CREDENTIALS_KEY": "${AI_BOT_KEY}", "TELEGRAM_WEBHOOK_ORIGIN": "https://demo.example.com",
           "CONTROLLED_PROVIDER_URL": "${SMOKE_CALLBACK_ORIGIN}", "PYTHONPATH": "/verification:/app"}
    agent = {**services["agent_service"]["environment"], "TELEGRAM_AI_ENABLED": "true",
             "TELEGRAM_AI_MODEL": "openai/gpt-oss-20b", "WEBHOOK_INTERNAL_URL": "http://webhook_service:8000",
             "WEBHOOK_AGENT_SERVICE_KEY": "${AI_CONTEXT_KEY}", "WEBHOOK_AGENT_INGRESS_KEY": "${AI_INGRESS_KEY}",
             "AGENT_WEBHOOK_REPLY_KEY": "${AI_REPLY_KEY}", "GROQ_API_KEY": "synthetic-groq-verification",
             "CONTROLLED_PROVIDER_URL": "${SMOKE_CALLBACK_ORIGIN}"}
    services["webhook_service"]["environment"] = web
    services["webhook_service"]["command"] = ["sh", "-c", "python -m alembic upgrade heads && exec uvicorn verify_telegram_ai:create_webhook_app --factory --host 0.0.0.0 --port 8000 --no-access-log"]
    services["agent_service"]["environment"] = agent
    services["callback"]["environment"].update(DATABASE_URL=web["DATABASE_URL"], VERIFICATION_ROLE="receiver")
    services["callback"]["command"] = ["python", "/verification/verify_telegram_ai.py", "--receiver"]
    for name, source, role, module, queue in (
        ("webhook_worker", "webhook_worker", "ingress", "verify_telegram_ai:celery_app", "celery"),
        ("agent_worker", "agent_worker", "generator", "verify_telegram_ai:celery_app", "telegram_ai"),
        ("agent_publisher", "agent_worker", "publisher", "app.workers.telegram_reply_worker:celery_app", "telegram_replies"),
        ("webhook_sender", "webhook_worker", "sender", "verify_telegram_ai:celery_app", "telegram_send"),
    ):
        services[name] = {**services[source], "environment": {**(web if name.startswith("webhook") else agent), "VERIFICATION_ROLE": role},
                          "command": ["celery", "-A", module, "worker", "--loglevel=warning", "--concurrency=1", "--queues=" + queue]}
    for name, service in services.items():
        if name not in {"postgres", "redis", "auth_service"}:
            if name == "agent_publisher":
                service["volumes"] = []
            if name not in {"callback", "agent_service"}:
                service["volumes"] = [*service.get("volumes", []), {"type": "bind", "source": str(Path(smoke.__file__).resolve()),
                    "target": "/verification/verify_stack.py", "read_only": True}]
            service["volumes"] = [*service.get("volumes", []), {"type": "bind", "source": str(Path(__file__).resolve()),
                "target": "/verification/verify_telegram_ai.py", "read_only": True}]
    if scanners:
        for name, (kind, module) in smoke.AI_SCANNERS.items():
            source = services["webhook_service" if kind == "web" else "agent_service"]
            services[name] = {**source, "init": True, "restart": "on-failure:2", "mem_limit": "128m",
                              "healthcheck": {"disable": True}, "volumes": [],
                              "command": ["python", "-m", module]}
    return config


def query(fixture, database, statement):
    smoke.require(database in {"auth_test", "webhook_test", "agent_test"}, "Foreign database rejected")
    return json.loads(fixture.compose("exec", "-T", "postgres", "psql", "-U", "smoke", "-d", database,
                                     "-At", "-v", "ON_ERROR_STOP=1", "-c", statement))


def recover(fixture):
    smoke.require(not fixture.scanners, "One-shot recovery forbidden in permanent scanner mode")
    for service, code in (
        ("webhook_service", "from scripts.recover_platform_outbox import scan_once; scan_once()"),
        ("agent_service", "from app.platform.processor import recover_jobs_once; from app.platform.replies import recover_replies_once; recover_jobs_once(); recover_replies_once()"),
        ("webhook_service", "from scripts.recover_telegram_answers import recover_answers_once; recover_answers_once()"),
    ):
        fixture.compose("exec", "-T", service, "python", "-c", code)


def consume_notifications(fixture, database, queue):
    smoke.require((database, queue) in {(2, "telegram_ai"), (2, "telegram_replies"), (1, "telegram_send")}, "Foreign queue fault rejected")
    fixture.owned()
    # Only new owned fixture notifications are consumed; durable rows stay intact.
    code = "local n=0; while redis.call('LPOP',KEYS[1]) do n=n+1 end; return n"
    count = int(fixture.compose("exec", "-T", "redis", "redis-cli", "-n", str(database), "EVAL", code, "1", queue))
    smoke.require(count >= 1, "No notification available for recovery fault")
    return count


def scanner_notification_fault(fixture, name, database, queue):
    markers = {"job_scanner": "Telegram job notification unavailable", "reply_scanner": "Telegram answer notification unavailable",
               "send_scanner": "Telegram send notification unavailable"}
    pairs = {"job_scanner": (2, "telegram_ai"), "reply_scanner": (2, "telegram_replies"), "send_scanner": (1, "telegram_send")}
    smoke.require(name in fixture.scanners and pairs.get(name) == (database, queue), "Foreign scanner fault rejected")
    fixture.stage = "broker notification recovery for " + name
    fixture.owned()
    fixture.compose("up", "-d", "--no-build", "--pull", "never", "--no-deps", name)
    original = fixture.owned()[name]
    before = fixture.compose("logs", "--no-color", "--tail", "100", name).count(markers[name])
    fixture.compose("stop", "--timeout", "10", "redis")
    smoke.wait_until(lambda: fixture.compose("logs", "--no-color", "--tail", "100", name).count(markers[name]) > before,
                     "Permanent scanner did not observe notification failure", 30)
    current = fixture.owned()[name]
    smoke.require(current["State"]["Running"] and current["Id"] == original["Id"] and
                  current["State"]["StartedAt"] == original["State"]["StartedAt"], "Scanner restarted on broker outage")
    fixture.compose("start", "redis")
    smoke.wait_until(lambda: fixture.owned()["redis"]["State"].get("Health", {}).get("Status") == "healthy", "Fixture broker did not recover")
    smoke.wait_until(lambda: int(fixture.compose("exec", "-T", "redis", "redis-cli", "-n", str(database), "LLEN", queue)) > 0,
                     "Scanner did not republish its durable notification", 30)
    fixture.compose("stop", "--timeout", "10", name)
    count = consume_notifications(fixture, database, queue)
    return {"consumed_notifications": count, "broker_outage_observed": True, "same_running_process": True}


def recover_with_scanners(fixture):
    dropped = {}
    fixture.compose("up", "-d", "--no-build", "--pull", "never", "--no-deps", "webhook_worker", "ingress_scanner")
    smoke.wait_until(lambda: query(fixture, "webhook_test", "SELECT to_json(coalesce(bool_and(state='published'),false)) FROM platform_ingress_outbox"),
                     "Permanent ingress scanner recovery failed", 90)
    smoke.require(query(fixture, "agent_test", "SELECT json_agg(state) FROM telegram_ai_jobs") == ["pending"], "AI stage advanced before its recovery probe")
    dropped["job_scanner"] = scanner_notification_fault(fixture, "job_scanner", 2, "telegram_ai")
    fixture.compose("up", "-d", "--no-build", "--pull", "never", "--no-deps", "agent_worker", "job_scanner")
    smoke.wait_until(lambda: query(fixture, "agent_test", "SELECT to_json(coalesce(bool_and(state='completed'),false)) FROM telegram_ai_jobs"),
                     "Permanent job scanner recovery failed", 90)
    smoke.require(query(fixture, "agent_test", "SELECT json_agg(state) FROM telegram_reply_outbox") == ["pending"], "Reply stage advanced before its recovery probe")
    dropped["reply_scanner"] = scanner_notification_fault(fixture, "reply_scanner", 2, "telegram_replies")
    fixture.compose("up", "-d", "--no-build", "--pull", "never", "--no-deps", "agent_publisher", "reply_scanner")
    smoke.wait_until(lambda: query(fixture, "agent_test", "SELECT to_json(coalesce(bool_and(state='published'),false)) FROM telegram_reply_outbox"),
                     "Permanent reply scanner recovery failed", 90)
    smoke.require(query(fixture, "webhook_test", "SELECT json_agg(state) FROM telegram_answers") == ["pending"], "Send stage advanced before its recovery probe")
    dropped["send_scanner"] = scanner_notification_fault(fixture, "send_scanner", 1, "telegram_send")
    fixture.compose("up", "-d", "--no-build", "--pull", "never", "--no-deps", "webhook_sender", "send_scanner")
    smoke.wait_until(lambda: query(fixture, "webhook_test", "SELECT to_json(coalesce(bool_and(state='succeeded' AND message_id=717),false)) FROM telegram_answers"),
                     "Permanent send scanner recovery failed", 90)
    return dropped


def verify(fixture):
    auth, web, agent = (fixture.url(name) for name in ("auth_service", "webhook_service", "agent_service"))
    http = fixture.http
    receipt = lambda: http(fixture.callback_origin + "/receipt")[1]
    account = {"email": f"ai-{fixture.project}@example.com", "username": "verification", "password": "Aa1!" + secrets.token_urlsafe(24)}
    smoke.expect(http(auth + "/api/v1/auth/register", "POST", account)[0], 200)
    status, login = http(auth + "/api/v1/auth/login", "POST", account)
    smoke.expect(status, 200)
    headers = {"Authorization": "Bearer " + login["access_token"]}
    status, tenant = http(auth + "/api/v1/tenants", "POST", {"name": "AI verification"}, headers)
    smoke.expect(status, 201)
    route = web + "/api/v1/tenants/" + str(UUID(tenant["id"])) + "/bots"
    status, bot = http(route, "POST", {"name": "Controlled bot", "token": TOKEN}, headers)
    smoke.expect(status, 201)
    bot_route = route + "/" + str(UUID(bot["id"]))
    smoke.expect(http(bot_route + "/webhook", "POST", {"dry_run": True}, headers)[0], 200)
    smoke.require(not receipt()["setup"], "Dry-run caused a setup effect")
    smoke.expect(http(bot_route + "/webhook", "POST", {"dry_run": False}, headers)[0], 200)
    setup = receipt()["setup"]
    smoke.require(len(setup) == 1, "Duplicate controlled setup")
    telegram_headers = {"X-Telegram-Bot-Api-Secret-Token": setup[0]["secret_token"]}
    intake = web + "/webhooks/telegram/" + bot["id"]
    payload = {"update_id": 42, "message": {"message_id": 9, "chat": {"id": 17, "type": "private"}, "text": "Synthetic question"}}
    for path in ("/mcp", "/mcp/sse", "/api/v1/documents", "/api/v1/conversations", "/api/v1/usage"):
        smoke.expect(http(agent + path)[0], 404)
    smoke.expect(http(intake, "POST", payload)[0], 401)
    for destination in (agent + "/internal/v1/telegram/updates", web + "/internal/v1/telegram/answers"):
        smoke.expect(http(destination, "POST", payload)[0], 401)
        smoke.expect(http(destination, "POST", payload, {"X-Webhook-Signature": "sha256=" + "0" * 64})[0], 401)
    print("PASS: real issuer tenant/bot, dry-run and closed unauthenticated/unscoped routes", flush=True)
    scanner_proof = {}
    if fixture.scanners:
        fixture.stage = "permanent scanners PostgreSQL outage"
        scanner_proof["processes"] = smoke.scanner_database_outage(fixture)
    fixture.stage = "broker outage admission"
    broker_before = fixture.owned()
    fixture.compose("stop", "--timeout", "10", "redis")
    status, admitted = http(intake, "POST", payload, telegram_headers)
    smoke.expect(status, 202)
    event_id = str(UUID(admitted["event_id"]))
    pending = query(fixture, "webhook_test", "SELECT json_build_array(state,attempts) FROM platform_ingress_outbox")
    smoke.require(pending == ["pending", 0], "Outage lost durable ingress")
    if fixture.scanners:
        smoke.wait_until(lambda: "platform_broker_unavailable" in fixture.compose("logs", "--no-color", "--tail", "100", "ingress_scanner"),
                         "Permanent ingress scanner did not observe broker outage", 30)
        broker_after = fixture.owned()
        smoke.require(all(broker_after[name]["State"]["Running"] and broker_after[name]["Id"] == broker_before[name]["Id"] and
                          broker_after[name]["State"]["StartedAt"] == broker_before[name]["State"]["StartedAt"] for name in fixture.scanners),
                      "Scanner exited or restarted on broker outage")
        fixture.compose("stop", "--timeout", "10", *fixture.scanners)
        scanner_proof["broker_outage_alive"] = True
    fixture.compose("start", "redis")
    fixture.stage = "controlled workers and recovery"
    if fixture.scanners:
        scanner_proof["consumed_notifications"] = recover_with_scanners(fixture)
        fixture.stage = "permanent scanners automatic restart"
        scanner_proof["restarts"] = smoke.restart_scanners(fixture)
        time.sleep(6)
    else:
        fixture.compose("up", "-d", "--no-build", "--pull", "never", "--no-deps", *WORKERS)
    fixture.items = fixture.owned()
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        if not fixture.scanners:
            recover(fixture)
        state = query(fixture, "webhook_test", "SELECT coalesce(json_agg(json_build_array(state,message_id)), '[]'::json) FROM telegram_answers")
        if state == [["succeeded", 717]]:
            break
        smoke.require(not any(row[0] in {"unknown", "failed"} for row in state), "Controlled send reached a terminal failure")
        time.sleep(1)
    smoke.require(state == [["succeeded", 717]], "Controlled reply deadline exceeded")
    fixture.stage = "duplicate, tenant and deactivation checks"
    smoke.expect(http(intake, "POST", payload, telegram_headers)[0], 200)
    changed = {**payload, "message": {**payload["message"], "text": "Changed"}}
    smoke.expect(http(intake, "POST", changed, telegram_headers)[0], 409)
    original = query(fixture, "webhook_test", "SELECT json_build_array(state,attempts,published_job_id) FROM platform_ingress_outbox")
    smoke.require(original[:2] == ["published", 2], "Lost admission receipt was not recovered once")
    job = query(fixture, "agent_test", "SELECT json_build_array(id,state,answer) FROM telegram_ai_jobs WHERE event_id='" + event_id + "'")
    smoke.require(job == [original[2], "completed", "Synthetic sender answer"], "Canonical result mismatch")
    counts = query(fixture, "agent_test", "SELECT json_build_object('jobs',(SELECT count(*) FROM telegram_ai_jobs),'usage',(SELECT count(*) FROM telegram_ai_usage),'reply_states',(SELECT json_agg(state) FROM telegram_reply_outbox),'conversations',(SELECT count(*) FROM conversations),'messages',(SELECT count(*) FROM messages),'legacy_usage',(SELECT count(*) FROM llm_usage_records))")
    smoke.require(counts == {"jobs": 1, "usage": 1, "reply_states": ["published"], "conversations": 0, "messages": 0, "legacy_usage": 0}, "Scoped/legacy result counts differ")
    foreign_account = {**account, "email": "foreign-" + fixture.project + "@example.com", "username": "foreign"}
    smoke.expect(http(auth + "/api/v1/auth/register", "POST", foreign_account)[0], 200)
    status, foreign_login = http(auth + "/api/v1/auth/login", "POST", foreign_account)
    smoke.expect(status, 200)
    foreign_headers = {"Authorization": "Bearer " + foreign_login["access_token"]}
    smoke.expect(http(auth + "/api/v1/tenants", "POST", {"name": "Foreign verification"}, foreign_headers)[0], 201)
    smoke.require(http(bot_route, headers=foreign_headers)[0] in {403, 404}, "Foreign tenant read accepted")
    smoke.require(http(bot_route + "/deactivate", "POST", headers=foreign_headers)[0] in {403, 404}, "Foreign tenant mutation accepted")
    smoke.expect(http(bot_route + "/deactivate", "POST", headers=headers)[0], 200)
    smoke.expect(http(intake, "POST", {"update_id": 43}, telegram_headers)[0], 403)
    if fixture.scanners:
        time.sleep(6)
    else:
        for _ in range(2):
            recover(fixture)
    records = receipt()
    smoke.require({key: records[key] for key in ("groq", "send", "lost_receipts", "errors")} ==
                  {"groq": 1, "send": 1, "lost_receipts": 1, "errors": 0}, "Duplicate or invalid controlled effect")
    smoke.require(query(fixture, "webhook_test", "SELECT count(*) FROM telegram_answers") == 1, "Duplicate send intent")
    print("PASS: broker/lost-receipt recovery, one job/usage/reply/canonical send, duplicate/conflict/tenant/deactivation", flush=True)
    return {"generation": 1, "usage": 1, "send": 1, "lost_receipts": 1, "publication_attempts": 2,
            "tenant_denial": True, "deactivation_denial": True, "legacy_tables_empty": True,
            "send_marker_committed_before_effect": True, "recovery": "permanent CLI loops" if fixture.scanners else "actual bounded one-shot scans",
            "scanner_proof": scanner_proof}


def main(argv=None):
    smoke.require(not sys.flags.optimize, "Optimized Python is not supported")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receiver", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scanners", action="store_true", help="Verify permanent recovery loops with owned outages/restarts")
    for kind, image in smoke.IMAGES.items():
        parser.add_argument(f"--{'webhook' if kind == 'web' else kind}-image", default=image)
    args = parser.parse_args(argv)
    if args.receiver:
        smoke.require(os.getenv("VERIFICATION_ROLE") == "receiver", "Receiver is fixture-only")
        server = ThreadingHTTPServer(("0.0.0.0", 8000), receiver_handler())
        signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return
    images = {kind: getattr(args, ("webhook" if kind == "web" else kind) + "_image") for kind in smoke.IMAGES}
    fixture = smoke.Fixture(images, controlled_ai=True, scanners=args.scanners, config_factory=ai_config)
    fixture.environment.update({key: secrets.token_hex(32) for key in ("AI_SERVICE_KEY", "AI_CONTEXT_KEY", "AI_INGRESS_KEY", "AI_REPLY_KEY")},
                               AI_BOT_KEY=Fernet.generate_key().decode(), SMOKE_CALLBACK_ORIGIN="http://127.0.0.1:8000")
    report = {"project": fixture.project, "images": fixture.images, "external_calls_enabled": False}
    try:
        fixture.start()
        report["callback_origin"] = fixture.callback_origin
        fixture.stage = "controlled issuer and setup"
        report["checks"] = verify(fixture)
        report["proof"] = fixture.proof()
        report["source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        report["fixture_source_sha256"] = hashlib.sha256(Path(smoke.__file__).read_bytes()).hexdigest()
        report["passed"] = True
    except Exception as error:
        report.update(passed=False, error_class=type(error).__name__, failed_stage=fixture.stage)
        if isinstance(error, smoke.VerificationError):
            report["failure_reason"] = str(error)
        raise
    finally:
        try:
            fixture.stop()
            report["owned_containers_stopped"] = True
        except Exception as error:
            report.update(passed=False, owned_containers_stopped=False, cleanup_error_class=type(error).__name__)
            raise
        finally:
            artifact = fixture.directory / "receipt.json"
            artifact.write_text(json.dumps(report, indent=2))
            print("RECEIPT: " + str(artifact), flush=True)
    # Keep this second acceptance sequential on the fixed-memory host.
    smoke.main([*(["--scanners"] if args.scanners else []), *[option for kind in images for option in (f"--{'webhook' if kind == 'web' else kind}-image", images[kind])]])


if os.getenv("VERIFICATION_ROLE") in {"ingress", "generator", "sender"}:
    install_worker_boundary()
    if os.environ["VERIFICATION_ROLE"] == "generator":
        from app.workers import telegram_worker
        celery_app = telegram_worker.celery_app
    else:
        from src.infrastructure.queue import celery_app as worker_module
        celery_app = worker_module.celery_app
elif __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - CLI failures must not expose fixture credentials.
        print("STOP: " + type(error).__name__ + "; details withheld", file=sys.stderr)
        raise SystemExit(1) from None
