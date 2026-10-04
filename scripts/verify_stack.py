"""Verify the local root stack and locate the Telegram/AgentHub contract gap.

Creates uniquely named demo records and retains them. No real provider calls are
made. Source/API-key provisioning uses the existing repository layer inside the
webhook container because public onboarding is incomplete. Credentials are never
printed or written to artifacts; the service uses its normal credential storage.
"""

import hashlib
import hmac
import json
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
AUTH = "http://127.0.0.1:28080"
WEBHOOK = "http://127.0.0.1:8001"
AGENT = "http://127.0.0.1:8014"


def request(url, method="GET", payload=None, headers=None):
    body = payload if isinstance(payload, bytes) else (
        json.dumps(payload).encode() if payload is not None else None
    )
    req = Request(url, data=body, method=method, headers={
        "Content-Type": "application/json", **(headers or {}),
    })
    try:
        response = urlopen(req, timeout=10)
    except HTTPError as exc:
        response = exc
    with response:
        raw = response.read()
        return response.status, json.loads(raw) if raw else None


def expect(status, expected):
    if status != expected:
        raise AssertionError(f"Expected HTTP {expected}, received {status}")


def provision(owner_id):
    code = '''
import asyncio, json, sys
from datetime import UTC, datetime
from uuid import UUID, uuid4
from src.domain.entities.source import Source
from src.infrastructure.db.base import async_session_maker
from src.infrastructure.db.repositories.api_key_repository import PostgresApiKeyRepository
from src.infrastructure.db.repositories.source_repository import PostgresSourceRepository
from src.infrastructure.db.repositories.user_repository import PostgresUserRepository
from src.services.auth_service import AuthService

async def main():
    data = json.load(sys.stdin)
    async with async_session_maker() as session:
        auth = AuthService(PostgresApiKeyRepository(session), PostgresUserRepository(session))
        _, key = await auth.create_api_key(UUID(data["owner_id"]), "nexus-stack-smoke")
        now = datetime.now(UTC)
        source = await PostgresSourceRepository(session).create(Source(
            id=uuid4(), created_at=now, updated_at=now, name="nexus-stack-smoke",
            slug=str(uuid4()), owner_id=UUID(data["owner_id"]),
            secret=data["secret"], is_active=True,
        ))
        print(json.dumps({"key": key, "source_id": str(source.id), "slug": source.slug}))

asyncio.run(main())
'''
    signing_secret = secrets.token_hex(32)
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "webhook_service", "python", "-c", code],
        input=json.dumps({"owner_id": owner_id, "secret": signing_secret}),
        capture_output=True, text=True, cwd=ROOT, timeout=30,
    )
    if result.returncode:
        raise RuntimeError("Test provisioning failed; captured output was withheld")
    return json.loads(result.stdout), signing_secret


def main():
    for base, path in ((AUTH, "/health"), (WEBHOOK, "/health/ready"), (AGENT, "/health")):
        expect(request(base + path)[0], 200)
    print("PASS: three root API health endpoints return 200")

    boundary = "nexus-" + uuid4().hex
    multipart = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="nexus-smoke.txt"\r\n'
        'Content-Type: text/plain\r\n\r\nSynthetic NexusCore document.\r\n'
        f'--{boundary}--\r\n'
    ).encode()
    status, document = request(AGENT + "/api/v1/documents", "POST", multipart, {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    expect(status, 202)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status, stored = request(AGENT + f"/api/v1/documents/{document['document_id']}")
        expect(status, 200)
        if stored["upload_status"] == "ready" and stored["chunk_count"] > 0:
            break
        if stored["upload_status"] == "failed":
            raise AssertionError("AgentHub embedding worker failed")
        time.sleep(0.2)
    else:
        raise AssertionError("AgentHub upload did not become ready")
    print("PASS: root AgentHub upload -> shared volume -> Celery -> PostgreSQL chunks (local fallback embeddings)")

    run_id = uuid4().hex
    password = secrets.token_urlsafe(24)
    email = f"nexus-{run_id}@example.com"
    expect(request(AUTH + "/api/v1/auth/register", "POST", {
        "email": email, "username": "nexus-" + run_id, "password": password,
    })[0], 200)
    status, tokens = request(AUTH + "/api/v1/auth/login", "POST", {
        "email": email, "password": password,
    })
    expect(status, 200)
    bearer = {"Authorization": "Bearer " + tokens["access_token"]}
    status, identity = request(AUTH + "/api/v1/auth/me", headers=bearer)
    expect(status, 200)
    if identity["email"] != email:
        raise AssertionError("AuthFortress returned a different identity")
    expect(request(AUTH + "/api/v1/auth/me")[0], 401)
    expect(request(AUTH + "/api/v1/auth/me", headers={"Authorization": "Bearer invalid"})[0], 401)
    expect(request(AUTH + "/api/v1/auth/login", "POST", {"email": email, "password": "wrong"})[0], 401)
    expect(request(WEBHOOK + "/api/v1/auth/keys", headers=bearer)[0], 401)
    print("PASS: login/JWT/me; missing/invalid JWT and wrong password rejected")
    print("CONFIRMED GAP: WebHook Manager does not accept AuthFortress bearer JWT (401)")

    status, user = request(WEBHOOK + "/api/v1/auth/register", "POST", {
        "email": email, "password": password,
    })
    expect(status, 201)
    auth, signing_secret = provision(user["user_id"])
    key_headers = {"X-API-Key": auth["key"]}
    received = []
    arrived = threading.Event()

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            signature = "sha256=" + hmac.new(signing_secret.encode(), body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(self.headers.get("X-Webhook-Signature", ""), signature):
                self.send_response(401)
                self.end_headers()
                return
            received.append((body, dict(self.headers)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"controlled local receiver")
            arrived.set()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", 0), Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, endpoint = request(WEBHOOK + "/api/v1/endpoints", "POST", {
            "name": "nexus-stack-smoke", "url": f"http://host.docker.internal:{server.server_port}/receive",
            "secret": signing_secret,
        }, key_headers)
        expect(status, 201)
        expect(request(WEBHOOK + "/api/v1/subscriptions", "POST", {
            "owner_id": user["user_id"], "source_id": auth["source_id"],
            "endpoint_id": endpoint["id"], "event_type_filter": ["nexus.telegram"],
        }, key_headers)[0], 201)
        payload = json.dumps({"update_id": 1, "message": {
            "message_id": 1, "chat": {"id": 1, "type": "private"},
            "text": "Synthetic NexusCore message",
        }}, separators=(",", ":")).encode()
        ingress = WEBHOOK + "/webhooks/ingest/" + auth["slug"]
        expect(request(ingress, "POST", payload)[0], 401)
        expect(request(ingress, "POST", payload, {
            "X-Telegram-Bot-Api-Secret-Token": signing_secret,
        })[0], 401)
        signature = "sha256=" + hmac.new(signing_secret.encode(), payload, hashlib.sha256).hexdigest()
        headers = {"X-Webhook-Signature": signature, "X-Idempotency-Key": run_id,
                   "X-Event-Type": "nexus.telegram"}
        status, event = request(ingress, "POST", payload, headers)
        expect(status, 202)
        status, duplicate = request(ingress, "POST", payload, headers)
        expect(status, 200)
        if duplicate["event_id"] != event["event_id"]:
            raise AssertionError("Duplicate produced a new event")
        if not arrived.wait(30):
            raise AssertionError("Real worker did not deliver the synthetic event")
        query = urlencode({"owner_id": user["user_id"], "event_id": event["event_id"]})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status, history = request(WEBHOOK + "/api/v1/deliveries?" + query, headers=key_headers)
            expect(status, 200)
            if history["items"] and history["items"][0]["status"] == "success":
                break
            time.sleep(0.2)
        else:
            raise AssertionError("Delivery was not recorded as successful")
        if len(received) != 1 or json.loads(received[0][0]) != json.loads(payload):
            raise AssertionError("Payload changed or duplicate was delivered")
        if any(name.lower() in {"authorization", "cookie", "x-api-key", "x-telegram-bot-api-secret-token"}
               for name in received[0][1]):
            raise AssertionError("Sensitive ingress headers reached the receiver")
        print("PASS: signed synthetic update -> root Redis/Celery -> local receiver; unchanged JSON values; sequential duplicate")
        print("CONFIRMED GAP: Telegram secret-token header alone is rejected (401); ingress requires HMAC")
        status, error = request(AGENT + "/api/v1/query", "POST", received[0][0])
        expect(status, 422)
        if not any(item["loc"] == ["body", "question"] for item in error["detail"]):
            raise AssertionError("Expected missing question validation error")
        print("CONFIRMED GAP: delivered Telegram JSON -> AgentHub query returns 422 (missing question)")
        print("NOT VERIFIED: tenant isolation, live Telegram/LLM, answer delivery, crash recovery")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
