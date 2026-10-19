"""Verify auth/upload/webhook contracts in a new isolated Compose project.

Uses cached images, an internal network and new test storage. Never selects the
existing root project or reads its .env. Stops owned containers; retains volumes
and a credential-free receipt. No real Telegram, LLM, OAuth or MCP calls.
"""

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
IMAGES = {
    "auth": "sha256:65256cebecb84ac274ad7726bcc12286ea8464f22651a2748f37f07dd45c5a6a",
    "web": "sha256:7cae10258f593cf22149130b306181ce26fa910542b96dc60582be9c333634d4",
    "agent": "sha256:2daa64d236fe947f52498260a852ea402a4f2fd74ffbc9d033da67a1c80c8b03",
    "postgres": "pgvector/pgvector:pg16",
    "redis": "redis:7-alpine",
}
KINDS = {"postgres": "postgres", "redis": "redis", "callback": "web",
         "auth_service": "auth", "webhook_service": "web", "webhook_worker": "web",
         "agent_service": "agent", "agent_worker": "agent"}
AI_KINDS = {**KINDS, "agent_publisher": "agent", "webhook_sender": "web"}
AI_SCANNERS = {"ingress_scanner": ("web", "scripts.recover_platform_outbox"),
               "job_scanner": ("agent", "scripts.recover_telegram_jobs"),
               "reply_scanner": ("agent", "scripts.recover_telegram_replies"),
               "send_scanner": ("web", "scripts.recover_telegram_answers")}
LEGACY_SCANNERS = {"legacy_scanner": ("web", "scripts.recover_legacy_deliveries")}
SCANNER_DATABASE_MARKERS = {"ingress_scanner": "platform_recovery_unavailable",
    "job_scanner": "Telegram job recovery unavailable", "reply_scanner": "Telegram answer recovery unavailable",
    "send_scanner": "Telegram send recovery unavailable", "legacy_scanner": "delivery_recovery_unavailable"}
FLAGS = ("PLATFORM_BOTS_ENABLED", "PLATFORM_TELEGRAM_ENABLED", "TELEGRAM_REPLIES_ENABLED",
         "PLATFORM_TENANT_ENABLED", "PLATFORM_READ_ENABLED", "TELEGRAM_AI_ENABLED")
EXTERNAL = ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "MCP_SERVERS", "MCP_SERVERS_CONFIG", "SENTRY_DSN")
LOAD_FILES = ("verify_local_load.py", "local_files.py")
LOAD_PATHS = {"auth_service": "/health", "webhook_service": "/health/ready", "agent_service": "/health"}


class VerificationError(ValueError):
    """Static verification failures may be reported without captured credentials."""


def require(condition, message):
    if not condition:
        raise VerificationError(message)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def request(url, method="GET", payload=None, headers=None, *, allowed_addresses=()):
    parsed = urlsplit(url)
    address = ipaddress.ip_address(parsed.hostname or "")
    require(parsed.scheme == "http" and parsed.hostname and
            (address.is_loopback or (str(address) in allowed_addresses and address.is_private and
                                    not address.is_link_local and not address.is_multicast and not address.is_unspecified)) and
            not parsed.username and not parsed.password and not parsed.fragment,
            "HTTP probes require loopback or inspected fixture addresses")
    body = payload if isinstance(payload, bytes) else (
        json.dumps(payload).encode() if payload is not None else None
    )
    req = Request(url, data=body, method=method, headers={
        "Content-Type": "application/json", **(headers or {}),
    })
    try:
        response = build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=10)
    except HTTPError as exc:
        response = exc
    with response:
        require(not 300 <= response.status < 400, "Probe redirect rejected")
        raw = response.read(1024 * 1024 + 1)
        require(len(raw) <= 1024 * 1024, "Probe response too large")
        return response.status, json.loads(raw) if raw else None


def expect(status, expected):
    require(status == expected, f"Expected HTTP {expected}, received {status}")


def wait_until(check, message, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(1)
    raise VerificationError(message)


def restart_scanners(fixture):
    """Kill only an inspected scanner child; let its bounded Docker policy restart it."""
    evidence = {}
    code = '''import os,signal,sys
from pathlib import Path
pids=[]
for entry in Path('/proc').iterdir():
    if not entry.name.isdecimal() or int(entry.name)<=1: continue
    try: parts=(entry/'cmdline').read_bytes().split(b'\\0')
    except (FileNotFoundError,PermissionError): continue
    if parts[:3]==[b'python',b'-m',sys.argv[1].encode()]: pids.append(int(entry.name))
if len(pids)!=1: raise RuntimeError('Scanner child identity mismatch')
os.kill(pids[0],signal.SIGKILL)
'''
    for name, (_, module) in fixture.scanners.items():
        original = fixture.owned()[name]
        require(original["State"]["Running"], "Scanner is not running before fault")
        fixture.compose("exec", "-T", name, "python", "-c", code, module)

        def restarted(name=name, original=original):
            current = fixture.owned()[name]
            require(current["Id"] == original["Id"] and not current["State"]["OOMKilled"], "Scanner identity/OOM changed")
            return current["State"]["Running"] and current["RestartCount"] > original["RestartCount"] and current["State"]["StartedAt"] != original["State"]["StartedAt"]

        wait_until(restarted, "Scanner automatic restart deadline exceeded", 45)
        evidence[name] = {"automatic_restart": True, "same_container": True}
    return evidence


def scanner_database_outage(fixture):
    fixture.compose("up", "-d", "--no-build", "--pull", "never", "--no-deps", *fixture.scanners)
    original = fixture.owned()
    before = {name: fixture.compose("logs", "--no-color", "--tail", "100", name).count(SCANNER_DATABASE_MARKERS[name])
              for name in fixture.scanners}
    fixture.compose("stop", "--timeout", "10", "postgres")
    wait_until(lambda: all(fixture.compose("logs", "--no-color", "--tail", "100", name).count(SCANNER_DATABASE_MARKERS[name]) > before[name]
                           for name in fixture.scanners), "Permanent scanners did not observe PostgreSQL outage", 40)
    current = fixture.owned()
    require(all(current[name]["State"]["Running"] and current[name]["Id"] == original[name]["Id"] and
                current[name]["State"]["StartedAt"] == original[name]["State"]["StartedAt"] for name in fixture.scanners),
            "Scanner exited or restarted during PostgreSQL outage")
    fixture.compose("start", "postgres")
    wait_until(lambda: fixture.owned()["postgres"]["State"].get("Health", {}).get("Status") == "healthy", "Fixture PostgreSQL did not recover")
    return {name: {"postgres_outage_observed": True, "same_running_process": True} for name in fixture.scanners}


def receiver_handler(signing_secret):
    records, lock = [], threading.Lock()

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
                    self.respond(200, {"records": list(records)})
            else:
                self.respond(404, {})

        def do_POST(self):
            if self.path != "/receive":
                self.respond(404, {})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                require(0 < size <= 1024 * 1024, "Invalid callback size")
                body = self.rfile.read(size)
                signature = "sha256=" + hmac.new(signing_secret.encode(), body, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(self.headers.get("X-Webhook-Signature", ""), signature):
                    self.respond(401, {})
                    return
                payload = json.loads(body)
            except (ValueError, UnicodeError):
                self.respond(400, {})
                return
            sensitive = {"authorization", "cookie", "x-api-key", "x-telegram-bot-api-secret-token"}
            with lock:
                records.append({"body": payload, "sensitive_headers": sorted(
                    name.lower() for name in self.headers if name.lower() in sensitive),
                    "delivery_id": self.headers.get("X-Delivery-ID")})
            self.respond(200, {"status": "received"})

        def log_message(self, *_):
            pass

    return Receiver


def create_agent_app():
    """Close the standalone MCP server only in this verification fixture."""
    from app.main import app
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def close_mcp(request, call_next):
        if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return await call_next(request)

    return app


def smoke_config(images, scanners=False):
    closed = {**dict.fromkeys(FLAGS, "false"), **dict.fromkeys(EXTERNAL, "")}
    common = {"restart": "no", "mem_limit": "256m", "security_opt": ["no-new-privileges:true"]}
    health = {"test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2)"],
              "interval": "2s", "timeout": "3s", "retries": 45}

    def database(driver, name):
        return f"postgresql+{driver}://smoke:${{SMOKE_DB_PASSWORD}}@postgres:5432/{name}_test"

    web = {**closed, "DATABASE_URL": database("asyncpg", "webhook"),
           "REDIS_URL": "redis://redis:6379/1", "CELERY_BROKER_URL": "redis://redis:6379/1",
           "SECRET_KEY": "${SMOKE_WEB_SECRET}", "DELIVERY_TRUSTED_ORIGINS": "${SMOKE_CALLBACK_ORIGINS}"}
    if scanners:
        web["RATE_LIMIT_INGEST"] = "8"
    agent = {**closed, "DATABASE_URL": database("psycopg", "agent"),
             "REDIS_URL": "redis://redis:6379/2", "CELERY_BROKER_URL": "redis://redis:6379/2",
             "LLM_PROVIDER": "gemini", "LLM_FALLBACK_PROVIDER": ""}
    services = {
        "postgres": {**common, "image": images["postgres"], "mem_limit": "192m",
                     "environment": {"POSTGRES_USER": "smoke", "POSTGRES_PASSWORD": "${SMOKE_DB_PASSWORD}"},
                     "volumes": ["postgres_data:/var/lib/postgresql/data"],
                     "healthcheck": {"test": ["CMD", "pg_isready", "-U", "smoke", "-d", "smoke"],
                                     "interval": "2s", "timeout": "3s", "retries": 45}},
        "redis": {**common, "image": images["redis"], "mem_limit": "64m", "volumes": ["redis_data:/data"],
                  "command": ["redis-server", "--save", "", "--appendonly", "no"],
                  "healthcheck": {"test": ["CMD", "redis-cli", "ping"], "interval": "2s", "timeout": "3s", "retries": 45}},
        "callback": {**common, "image": images["web"], "mem_limit": "192m",
                     "environment": {"SMOKE_RECEIVER": "1", "SMOKE_SIGNING_SECRET": "${SMOKE_SIGNING_SECRET}"},
                     "volumes": [{"type": "bind", "source": str(Path(__file__).resolve()),
                                  "target": "/verification/verify_stack.py", "read_only": True}],
                     "command": ["python", "/verification/verify_stack.py", "--receiver"], "healthcheck": health},
        "auth_service": {**common, "image": images["auth"], "environment": {
            "DATABASE_URL": database("psycopg2", "auth"), "REDIS_URL": "redis://redis:6379/0",
            "JWT_SECRET_KEY": "${SMOKE_AUTH_SECRET}"}, "healthcheck": health,
            "command": ["sh", "-c", "python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]},
        "webhook_service": {**common, "image": images["web"], "environment": web,
            "healthcheck": {**health, "test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=2)"]},
            "command": ["sh", "-c", "python -m alembic upgrade heads && exec uvicorn src.api.main:app --host 0.0.0.0 --port 8000"]},
        "webhook_worker": {**common, "image": images["web"], "environment": web,
            "command": ["celery", "-A", "src.infrastructure.queue.celery_app", "worker", "--loglevel=warning", "--concurrency=1"]},
        "agent_service": {**common, "image": images["agent"], "environment": {**agent, "PYTHONPATH": "/verification:/app"},
            "volumes": ["uploads:/app/uploads", {"type": "bind", "source": str(Path(__file__).resolve()),
                        "target": "/verification/verify_stack.py", "read_only": True}], "healthcheck": health,
            "command": ["uvicorn", "verify_stack:create_agent_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]},
        "agent_worker": {**common, "image": images["agent"], "environment": agent,
            "volumes": ["uploads:/app/uploads"],
            "command": ["celery", "-A", "app.workers.embed_worker.celery_app", "worker", "--loglevel=warning", "--concurrency=1"]},
    }
    if scanners:
        services["legacy_scanner"] = {**common, "image": images["web"], "environment": web,
            "init": True, "restart": "on-failure:2", "mem_limit": "128m",
            "command": ["python", "-m", LEGACY_SCANNERS["legacy_scanner"][1]]}
    for name in LOAD_PATHS:
        services[name]["volumes"] = [*services[name].get("volumes", []), *[
            {"type": "bind", "source": str(Path(__file__).with_name(filename).resolve()),
             "target": "/verification/" + filename, "read_only": True} for filename in LOAD_FILES]]
    return {"services": services, "networks": {"default": {"internal": True}},
            "volumes": {"uploads": {}, "postgres_data": {}, "redis_data": {}}}


def traffic_settings(name, environment, controlled_ai=False):
    enabled = set()
    if controlled_ai and name in {"webhook_service", "webhook_worker", "webhook_sender", "ingress_scanner", "send_scanner"}:
        enabled = {"PLATFORM_BOTS_ENABLED", "PLATFORM_TELEGRAM_ENABLED", "TELEGRAM_REPLIES_ENABLED"}
    elif controlled_ai and name in {"agent_service", "agent_worker", "agent_publisher", "job_scanner", "reply_scanner"}:
        enabled = {"TELEGRAM_AI_ENABLED"}
    require(all(str(environment.get(flag, "false")).lower() == str(flag in enabled).lower()
                for flag in FLAGS), "Unexpected platform flag")
    for key in EXTERNAL:
        expected = "synthetic-groq-verification" if controlled_ai and name in {
            "agent_service", "agent_worker", "agent_publisher", "job_scanner", "reply_scanner"} and key == "GROQ_API_KEY" else ""
        require(environment.get(key, "") == expected, "External traffic credentials configured")
    if controlled_ai and enabled:
        if "TELEGRAM_AI_ENABLED" in enabled:
            require(environment.get("WEBHOOK_INTERNAL_URL") == "http://webhook_service:8000" and
                    environment.get("TELEGRAM_AI_MODEL") == "openai/gpt-oss-20b", "Unexpected controlled AI configuration")
        else:
            require(environment.get("AUTHFORTRESS_BASE_URL") == "http://auth_service:8000" and
                    environment.get("AGENTHUB_BASE_URL") == "http://agent_service:8000" and
                    environment.get("TELEGRAM_WEBHOOK_ORIGIN") == "https://demo.example.com", "Unexpected controlled service origins")


def fixture_subnet(project):
    return f"10.{int(project[-4:-2], 16)}.{int(project[-2:], 16)}.0/24"


def validate_config(config, project, images, controlled_ai=False, scanners=False):
    scanner_roles = (AI_SCANNERS if controlled_ai else LEGACY_SCANNERS) if scanners else {}
    kinds = {**(AI_KINDS if controlled_ai else KINDS), **{name: role[0] for name, role in scanner_roles.items()}}
    require(project.startswith("nexus-smoke-") and len(project) == 44, "Invalid fixture project")
    require(config["name"] == project and set(config["services"]) == set(kinds), "Unexpected fixture services")
    require(set(config["networks"]) == {"default"} and config["networks"]["default"]["internal"], "Fixture network must be internal")
    require(not config["networks"]["default"].get("external") and not config["networks"]["default"].get("driver_opts"), "External network options rejected")
    require(config["networks"]["default"]["name"] == project + "_default", "Unexpected fixture network name")
    if config["networks"]["default"].get("ipam"):
        require(config["networks"]["default"]["ipam"] == {"config": [{"subnet": fixture_subnet(project)}]}, "Unexpected fixture subnet")
    require(set(config["volumes"]) == {"uploads", "postgres_data", "redis_data"} and all(
        volume["name"] == project + "_" + key for key, volume in config["volumes"].items()), "Unexpected fixture volume")
    require(all(not volume.get("external") and not volume.get("driver_opts") and
                volume.get("driver", "local") == "local" for volume in config["volumes"].values()), "External volume options rejected")
    for name, service in config["services"].items():
        require(service["image"] == images[kinds[name]], "Unexpected fixture image")
        require(set(service.get("networks", {})) == {"default"}, "Unexpected service network")
        require(not any(service.get(key) for key in ("container_name", "build", "privileged", "network_mode", "env_file", "extra_hosts")), "Unsafe fixture option")
        require(not service.get("ports"), "Fixture must not publish host ports")
        if name in scanner_roles:
            require(service.get("init") and service.get("restart") == "on-failure:2" and
                    service["command"] == ["python", "-m", scanner_roles[name][1]], "Unexpected permanent scanner entrypoint/policy")
        for volume in service.get("volumes", []):
            mounts = {"postgres": ("postgres_data", "/var/lib/postgresql/data"), "redis": ("redis_data", "/data"),
                      "agent_service": ("uploads", "/app/uploads"), "agent_worker": ("uploads", "/app/uploads")}
            allowed = (volume["type"] == "volume" and name in mounts and
                       (volume["source"], volume["target"]) == mounts[name]) or (
                       volume["type"] == "bind" and volume.get("read_only") and (
                           Path(volume["source"]) == Path(__file__).resolve() and
                           volume["target"] == "/verification/verify_stack.py" and (name in {"callback", "agent_service"}
                           or controlled_ai and name not in {"postgres", "redis", "auth_service"})
                           or controlled_ai and name not in {"postgres", "redis"} and
                           Path(volume["source"]) == Path(__file__).with_name("verify_telegram_ai.py").resolve() and
                           volume["target"] == "/verification/verify_telegram_ai.py"
                           or name in LOAD_PATHS and any(
                               Path(volume["source"]) == Path(__file__).with_name(filename).resolve() and
                               volume["target"] == "/verification/" + filename for filename in LOAD_FILES)))
            require(allowed, "Unsafe fixture mount")
        environment = service.get("environment", {})
        traffic_settings(name, environment, controlled_ai)
        if "DATABASE_URL" in environment:
            parsed = urlsplit(environment["DATABASE_URL"])
            require(parsed.hostname == "postgres" and parsed.path in {"/auth_test", "/webhook_test", "/agent_test"}, "Database must belong to fixture")
        for key in ("REDIS_URL", "CELERY_BROKER_URL"):
            if key in environment:
                require(urlsplit(environment[key]).hostname == "redis", "Broker must belong to fixture")


class Fixture:
    def __init__(self, images, *, controlled_ai=False, scanners=False, config_factory=smoke_config):
        self.controlled_ai = controlled_ai
        self.scanners = (AI_SCANNERS if controlled_ai else LEGACY_SCANNERS) if scanners else {}
        self.kinds = {**(AI_KINDS if controlled_ai else KINDS), **{name: role[0] for name, role in self.scanners.items()}}
        self.project = "nexus-smoke-" + uuid4().hex
        self.directory = ROOT / ".venv" / self.project
        self.directory.mkdir(parents=True, exist_ok=False)
        self.environment = {**os.environ, "SMOKE_CALLBACK_ORIGINS": "[]", **{
            key: secrets.token_hex(32) for key in ("SMOKE_DB_PASSWORD", "SMOKE_AUTH_SECRET", "SMOKE_WEB_SECRET", "SMOKE_SIGNING_SECRET")}}
        self.images = {kind: json.loads(self.run(["docker", "image", "inspect", image]))[0]["Id"]
                       for kind, image in images.items()}
        config = config_factory(self.images, scanners=True) if scanners else config_factory(self.images)
        config["networks"]["default"]["ipam"] = {"config": [{"subnet": fixture_subnet(self.project)}]}
        (self.directory / "compose.json").write_text(json.dumps(config))
        (self.directory / "empty.env").write_text("")
        self.prefix = ["docker", "compose", "--project-name", self.project, "--project-directory", str(self.directory),
                       "--env-file", str(self.directory / "empty.env"), "-f", str(self.directory / "compose.json")]

    def run(self, command, data=None):
        result = subprocess.run(command, input=data, capture_output=True, text=True,
                                env=self.environment, cwd=ROOT, timeout=180, check=False)
        if result.returncode:
            raise RuntimeError("Fixture command failed; captured output withheld")
        return result.stdout.strip()

    def compose(self, *arguments, data=None):
        return self.run([*self.prefix, *arguments], data)

    def config(self):
        self.compose("config", "--quiet")
        validate_config(json.loads(self.compose("config", "--format", "json")), self.project, self.images, self.controlled_ai, bool(self.scanners))

    def owned(self, *, cleanup=False):
        ids = self.compose("ps", "--all", "--quiet").splitlines()
        if not ids:
            return {}
        items = json.loads(self.run(["docker", "inspect", *ids]))
        network = json.loads(self.run(["docker", "network", "inspect", self.project + "_default"]))[0]
        require(network["Internal"] and network["Labels"]["com.docker.compose.project"] == self.project, "Network ownership mismatch")
        require([item["Subnet"] for item in network["IPAM"]["Config"]] == [fixture_subnet(self.project)], "Actual fixture subnet mismatch")
        result = {}
        for item in items:
            labels = item["Config"]["Labels"]
            name = labels["com.docker.compose.service"]
            require(labels["com.docker.compose.project"] == self.project and name in self.kinds, "Container ownership mismatch")
            require(name not in result, "Duplicate fixture service instance")
            require(item["Image"] == self.images[self.kinds[name]], "Container image mismatch")
            require(set(item["NetworkSettings"]["Networks"]) == {self.project + "_default"}, "Container network mismatch")
            require(not item["HostConfig"].get("PortBindings") and not item["HostConfig"].get("PublishAllPorts"), "Unexpected host publication")
            if name in self.scanners:
                policy = item["HostConfig"]["RestartPolicy"]
                expected = {"Name": "on-failure", "MaximumRetryCount": 2}
                require(item["HostConfig"].get("Init") and
                        (policy == expected or cleanup and policy == {"Name": "no", "MaximumRetryCount": 0}) and
                        item["Config"]["Cmd"] == ["python", "-m", self.scanners[name][1]], "Actual scanner entrypoint/policy mismatch")
            environment = dict(value.split("=", 1) for value in item["Config"]["Env"] if "=" in value)
            traffic_settings(name, environment, self.controlled_ai)
            if self.controlled_ai and name not in {"postgres", "redis", "callback", "auth_service"}:
                require(environment.get("CONTROLLED_PROVIDER_URL") == self.callback_origin, "Controlled provider is outside owned callback")
            for mount in item["Mounts"]:
                if mount["Type"] == "volume":
                    mounts = {"postgres": ("postgres_data", "/var/lib/postgresql/data"), "redis": ("redis_data", "/data"),
                              "agent_service": ("uploads", "/app/uploads"), "agent_worker": ("uploads", "/app/uploads")}
                    require(name in mounts and (mount["Name"], mount["Destination"]) ==
                            (self.project + "_" + mounts[name][0], mounts[name][1]), "Existing volume selected")
                    volume = json.loads(self.run(["docker", "volume", "inspect", mount["Name"]]))[0]
                    require(volume["Labels"]["com.docker.compose.project"] == self.project, "Volume ownership mismatch")
                    require(volume["Driver"] == "local" and not volume.get("Options"), "Existing physical storage options selected")
                elif mount["Type"] == "bind":
                    require(not mount["RW"] and (
                        (name in {"callback", "agent_service"} or self.controlled_ai and name not in {"postgres", "redis", "auth_service"})
                        and mount["Destination"] == "/verification/verify_stack.py"
                        or self.controlled_ai and name not in {"postgres", "redis"} and
                        mount["Destination"] == "/verification/verify_telegram_ai.py"
                        or name in LOAD_PATHS and mount["Destination"] in {
                            "/verification/" + filename for filename in LOAD_FILES}), "Unexpected bind mount")
                else:
                    require(mount["Type"] == "tmpfs", "Unexpected container storage")
            result[name] = item
        return result

    def url(self, name):
        item = self.items[name]
        address = item["NetworkSettings"]["Networks"][self.project + "_default"]["IPAddress"]
        ip = ipaddress.IPv4Address(address)
        require(ip.is_private and not ip.is_loopback and not ip.is_link_local, "Unsafe fixture address")
        return f"http://{ip}:8000"

    def http(self, url, method="GET", payload=None, headers=None):
        parsed = urlsplit(url)
        require(parsed.scheme == "http" and parsed.hostname in self.addresses and parsed.port == 8000 and
                not parsed.username and not parsed.password and not parsed.fragment, "HTTP target is outside owned fixture")
        data = {"url": url, "method": method, "headers": headers, "addresses": self.addresses,
                "payload": base64.b64encode(payload).decode() if isinstance(payload, bytes) else payload,
                "binary": isinstance(payload, bytes)}
        code = '''import base64,json,sys
sys.path.insert(0,'/verification')
from verify_stack import request
data=json.load(sys.stdin)
payload=base64.b64decode(data['payload']) if data['binary'] else data['payload']
print(json.dumps(request(data['url'],data['method'],payload,data['headers'],allowed_addresses=data['addresses'])))
'''
        return json.loads(self.compose("exec", "-T", "callback", "python", "-c", code, data=json.dumps(data)))

    def start(self):
        self.stage = "fixture configuration"
        self.config()
        require(not self.compose("ps", "--all", "--quiet"), "Fixture project already exists")
        self.stage = "fixture infrastructure"
        self.compose("up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "120", "postgres", "redis", "callback")
        callback = self.owned()["callback"]
        address = callback["NetworkSettings"]["Networks"][self.project + "_default"]["IPAddress"]
        ip = ipaddress.IPv4Address(address)
        require(ip.is_private and not ip.is_loopback and not ip.is_link_local, "Unsafe callback address")
        self.callback_origin = f"http://{ip}:8000"
        self.environment["SMOKE_CALLBACK_ORIGINS"] = json.dumps([self.callback_origin])
        self.environment["SMOKE_CALLBACK_ORIGIN"] = self.callback_origin
        self.config()
        print("PASS: owned internal network and exact numeric callback origin", flush=True)
        self.stage = "fixture migrations"
        self.compose("exec", "-T", "postgres", "psql", "-U", "smoke", "-d", "smoke", "-v", "ON_ERROR_STOP=1",
                     data="CREATE DATABASE auth_test; CREATE DATABASE webhook_test; CREATE DATABASE agent_test;")
        self.compose("run", "--rm", "--no-deps", "agent_service", "python", "-m", "alembic", "upgrade", "head")
        self.stage = "fixture APIs"
        self.compose("up", "-d", "--no-build", "--pull", "never", "--no-deps", "--wait", "--wait-timeout", "120", "auth_service", "webhook_service", "agent_service")
        self.stage = "fixture workers"
        if not self.controlled_ai:
            self.compose("up", "-d", "--no-build", "--pull", "never", "--no-deps", "webhook_worker", "agent_worker")
            if self.scanners:
                self.compose("up", "-d", "--no-build", "--pull", "never", "--no-deps", *self.scanners)
        self.items = self.owned()
        expected = set(self.kinds) - set(self.scanners) - {"webhook_worker", "agent_worker", "webhook_sender", "agent_publisher"} if self.controlled_ai else set(self.kinds)
        require(set(self.items) == expected, "Incomplete fixture")
        self.addresses = [urlsplit(self.url(name)).hostname for name in self.items]

    def stop(self):
        items = self.owned(cleanup=True)
        scanner_ids = [items[name]["Id"] for name in self.scanners if name in items]
        applications = [name for name, item in items.items()
                        if name not in {"postgres", "redis", "callback"} and item["State"]["Running"]]
        try:
            if scanner_ids:
                self.run(["docker", "update", "--restart=no", *scanner_ids])
            if applications:
                self.compose("stop", "--timeout", "30", *applications)
        finally:
            self.compose("stop", "--timeout", "10")
        items = self.owned(cleanup=True)
        require(all(not item["State"]["Running"] for item in items.values()), "Fixture did not stop")
        require(all(not item["State"]["OOMKilled"] for item in items.values()), "Fixture cleanup observed OOM")
        require(all(item["State"]["ExitCode"] in ({0, 143} if name in self.scanners else {0})
                    for name, item in items.items()), "Fixture cleanup observed unexpected exit code")
        require(all(items[name]["HostConfig"]["RestartPolicy"] == {"Name": "no", "MaximumRetryCount": 0}
                    for name in self.scanners if name in items), "Fixture scanner restart remains enabled")

    def proof(self):
        items = self.owned()
        require(all(item["State"]["Running"] and not item["State"]["OOMKilled"] for item in items.values()), "Fixture process stopped or OOM killed")
        require(set(items) == set(self.kinds), "Incomplete fixture proof")
        for name in set(self.kinds) - {"postgres", "redis"}:
            uid = self.compose("exec", "-T", name, "python", "-c", "import os; print(os.getuid())")
            require(uid == "10001", "Application fixture UID mismatch")
        versions = {}
        for database, expected in (("auth_test", {"004_tenants"}), ("webhook_test", {"8f3b1c6d2a90", "c42d8e91a730"}), ("agent_test", {"003_tenant_resources"})):
            version = self.compose("exec", "-T", "postgres", "psql", "-U", "smoke", "-d", database, "-At", "-c", "SELECT version_num FROM alembic_version")
            require(set(version.splitlines()) == expected, "Fixture migration head mismatch")
            versions[database] = sorted(version.splitlines())
        if self.controlled_ai:
            return {"revisions": versions, "application_uid": 10001, "processes_running_without_oom": len(items),
                    **({"all_ten_processes_running_without_oom": True} if not self.scanners else {}),
                    "permanent_scanners": list(self.scanners), "probe_transport": "owned callback exec, inspected IP allowlist"}
        web = json.loads(self.compose("exec", "-T", "postgres", "psql", "-U", "smoke", "-d", "webhook_test", "-At", "-c",
            "SELECT json_build_object('events',(SELECT count(*) FROM webhook_events),'deliveries',(SELECT count(*) FROM delivery_attempts),'success',(SELECT count(*) FROM delivery_attempts WHERE lower(status::text)='success'))"))
        require(web == {"events": 2, "deliveries": 2, "success": 2}, "Fixture durable event/delivery counts differ")
        return {"revisions": versions, "webhook_rows": web, "application_uid": 10001,
                "processes_running_without_oom": len(items), "permanent_scanners": list(self.scanners),
                **({"all_eight_processes_running_without_oom": True} if not self.scanners else {}),
                "probe_transport": "owned callback exec, inspected IP allowlist"}


def provision(fixture, owner_id):
    code = '''
import asyncio,json,sys
from datetime import UTC,datetime
from uuid import UUID,uuid4
from src.domain.entities.source import Source
from src.infrastructure.db.base import async_session_maker
from src.infrastructure.db.repositories.api_key_repository import PostgresApiKeyRepository
from src.infrastructure.db.repositories.source_repository import PostgresSourceRepository
from src.infrastructure.db.repositories.user_repository import PostgresUserRepository
from src.services.auth_service import AuthService
async def main():
 data=json.load(sys.stdin)
 async with async_session_maker() as session:
  auth=AuthService(PostgresApiKeyRepository(session),PostgresUserRepository(session))
  _,key=await auth.create_api_key(UUID(data['owner_id']),'isolated-stack-smoke')
  now=datetime.now(UTC)
  source=await PostgresSourceRepository(session).create(Source(id=uuid4(),created_at=now,updated_at=now,
   name='isolated-stack-smoke',slug=str(uuid4()),owner_id=UUID(data['owner_id']),secret=data['secret'],is_active=True))
  print(json.dumps({'key':key,'source_id':str(source.id),'slug':source.slug}))
asyncio.run(main())
'''
    fixture.owned()
    secret = fixture.environment["SMOKE_SIGNING_SECRET"]
    return json.loads(fixture.compose("exec", "-T", "webhook_service", "python", "-c", code,
                      data=json.dumps({"owner_id": owner_id, "secret": secret}))), secret


def verify(fixture):
    request = fixture.http
    fixture.stage = "inspected internal API addresses"
    auth, web, agent, callback = (fixture.url(name) for name in ("auth_service", "webhook_service", "agent_service", "callback"))
    fixture.stage = "fixture HTTP health"
    for base, path in ((auth, "/health"), (web, "/health/ready"), (agent, "/health")):
        expect(request(base + path)[0], 200)
    expect(request(agent + "/mcp/sse")[0], 404)
    fixture.stage = "upload and embedding worker"
    boundary = "nexus-" + uuid4().hex
    multipart = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="nexus-smoke.txt"\r\n'
                 'Content-Type: text/plain\r\n\r\nSynthetic NexusCore document.\r\n'
                 f'--{boundary}--\r\n').encode()
    status, document = request(agent + "/api/v1/documents", "POST", multipart, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    expect(status, 202)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status, stored = request(agent + f"/api/v1/documents/{document['document_id']}")
        expect(status, 200)
        if stored["upload_status"] == "ready" and stored["chunk_count"] > 0:
            break
        require(stored["upload_status"] != "failed", "Embedding worker failed")
        time.sleep(0.2)
    else:
        raise RuntimeError("Upload deadline exceeded")
    print("PASS: isolated upload/shared volume/Celery/PostgreSQL chunks; fallback embeddings")

    fixture.stage = "auth contracts"
    run_id, password = uuid4().hex, secrets.token_urlsafe(24)
    email = f"nexus-{run_id}@example.com"
    expect(request(auth + "/api/v1/auth/register", "POST", {"email": email, "username": "nexus-" + run_id, "password": password})[0], 200)
    status, tokens = request(auth + "/api/v1/auth/login", "POST", {"email": email, "password": password})
    expect(status, 200)
    bearer = {"Authorization": "Bearer " + tokens["access_token"]}
    status, identity = request(auth + "/api/v1/auth/me", headers=bearer)
    expect(status, 200)
    require(identity["email"] == email, "Different auth identity")
    expect(request(auth + "/api/v1/auth/me")[0], 401)
    expect(request(auth + "/api/v1/auth/me", headers={"Authorization": "Bearer invalid"})[0], 401)
    expect(request(auth + "/api/v1/auth/login", "POST", {"email": email, "password": "wrong"})[0], 401)
    expect(request(web + "/api/v1/auth/keys", headers=bearer)[0], 401)
    print("PASS: login/JWT/me and missing/invalid/wrong-credential denials")

    fixture.stage = "webhook contracts"
    status, user = request(web + "/api/v1/auth/register", "POST", {"email": email, "password": password})
    expect(status, 201)
    source, signing_secret = provision(fixture, user["user_id"])
    key_headers = {"X-API-Key": source["key"]}
    expect(request(web + "/api/v1/endpoints", "POST", {"name": "blocked", "url": "http://127.0.0.1:1/receive", "secret": signing_secret}, key_headers)[0], 422)
    status, endpoint = request(web + "/api/v1/endpoints", "POST", {"name": "isolated-smoke", "url": fixture.callback_origin + "/receive", "secret": signing_secret}, key_headers)
    expect(status, 201)
    expect(request(web + "/api/v1/subscriptions", "POST", {"owner_id": user["user_id"], "source_id": source["source_id"], "endpoint_id": endpoint["id"], "event_type_filter": ["nexus.telegram"]}, key_headers)[0], 201)
    payload = json.dumps({"update_id": 1, "message": {"message_id": 1, "chat": {"id": 1, "type": "private"}, "text": "Synthetic NexusCore message"}}, separators=(",", ":")).encode()
    ingress = web + "/webhooks/ingest/" + source["slug"]
    expect(request(ingress, "POST", payload)[0], 401)
    expect(request(ingress, "POST", payload, {"X-Telegram-Bot-Api-Secret-Token": signing_secret})[0], 401)
    expect(request(ingress, "POST", payload, {"X-Webhook-Signature": "sha256=" + "0" * 64})[0], 401)
    signature = "sha256=" + hmac.new(signing_secret.encode(), payload, hashlib.sha256).hexdigest()
    headers = {"X-Webhook-Signature": signature, "X-Idempotency-Key": run_id, "X-Event-Type": "nexus.telegram",
               "Authorization": "Bearer synthetic-unused", "Cookie": "synthetic-unused", **key_headers,
               "X-Telegram-Bot-Api-Secret-Token": signing_secret}
    if fixture.scanners:
        fixture.stage = "legacy scanner PostgreSQL outage"
        scanner_database_outage(fixture)
        fixture.stage = "legacy admission without Redis"
        fixture.owned()
        fixture.compose("stop", "--timeout", "10", "legacy_scanner", "webhook_worker")
        fixture.compose("stop", "--timeout", "10", "redis")
        expect(request(ingress, "POST", payload, {"X-Webhook-Signature": "sha256=" + "0" * 64})[0], 401)
        expect(request(web + "/api/v1/endpoints", headers={"X-API-Key": "synthetic-invalid"})[0], 401)
    status, event = request(ingress, "POST", payload, headers)
    expect(status, 202)
    status, duplicate = request(ingress, "POST", payload, headers)
    expect(status, 200)
    require(duplicate["event_id"] == event["event_id"], "Duplicate produced new event")
    concurrent_headers = {**headers, "X-Idempotency-Key": run_id + "-concurrent"}
    with ThreadPoolExecutor(max_workers=4) as clients:
        admissions = list(clients.map(lambda _: request(ingress, "POST", payload, concurrent_headers), range(4)))
    require(sorted(status for status, _ in admissions) == [200, 200, 200, 202], "Concurrent admission duplicated")
    require(len({item["event_id"] for _, item in admissions}) == 1, "Concurrent event IDs differ")
    if fixture.scanners:
        fixture.stage = "legacy rate quota without Redis"
        quota_headers = {**headers, "X-API-Key": "wh_quota-synthetic"}
        for _ in range(8):
            expect(request(ingress, "POST", payload, quota_headers)[0], 200)
        expect(request(ingress, "POST", payload, quota_headers)[0], 429)
        code = "import asyncio; from src.infrastructure.cache.rate_limiter import RateLimiter; print(asyncio.run(RateLimiter().allow(key='ingest:wh_quota',limit=8)))"
        require(fixture.compose("exec", "-T", "webhook_service", "python", "-c", code) == "False", "Another API process reset quota")
        fixture.stage = "legacy API restart without Redis"
        original = fixture.owned()["webhook_service"]
        fixture.compose("stop", "--timeout", "10", "webhook_service")
        fixture.compose("start", "webhook_service")
        current = fixture.owned()["webhook_service"]
        require(current["Id"] == original["Id"] and current["State"]["StartedAt"] != original["State"]["StartedAt"], "API restart identity mismatch")
        previous_address = urlsplit(web).hostname
        fixture.items["webhook_service"] = current
        web = fixture.url("webhook_service")
        fixture.addresses = [address for address in fixture.addresses if address != previous_address] + [urlsplit(web).hostname]
        ingress = web + "/webhooks/ingest/" + source["slug"]

        def api_live():
            try:
                return request(web + "/health/live")[0] == 200
            except RuntimeError:
                return False

        wait_until(api_live, "API did not recover without Redis", 30)
        status, readiness = request(web + "/health/ready")
        expect(status, 503)
        require(readiness == {"status": "unavailable", "database": "ok", "redis": "unavailable"}, "Incorrect offline API readiness")
        expect(request(ingress, "POST", payload, quota_headers)[0], 429)
        status, duplicate = request(ingress, "POST", payload, headers)
        expect(status, 200)
        require(duplicate["event_id"] == event["event_id"], "API restart lost original event")
        expect(request(ingress, "POST", payload, {"X-Webhook-Signature": "sha256=" + "0" * 64})[0], 401)
        print("PASS: API restart without Redis retains quota/event and live200/ready503/HMAC contracts", flush=True)
        fixture.stage = "legacy scanner broker outage"
        fixture.owned()
        fixture.compose("start", "legacy_scanner")
        before = fixture.owned()["legacy_scanner"]
        wait_until(lambda: "delivery_broker_unavailable" in fixture.compose("logs", "--no-color", "--tail", "100", "legacy_scanner"),
                   "Legacy scanner did not observe broker outage", 60)
        current = fixture.owned()["legacy_scanner"]
        require(current["State"]["Running"] and current["State"]["StartedAt"] == before["State"]["StartedAt"], "Legacy scanner exited on broker outage")
        fixture.compose("start", "redis")
        wait_until(lambda: fixture.owned()["redis"]["State"].get("Health", {}).get("Status") == "healthy", "Fixture broker recovery failed")
        expect(request(ingress, "POST", payload, quota_headers)[0], 429)
        fixture.compose("start", "webhook_worker")
    events = [event["event_id"], admissions[0][1]["event_id"]]
    for event_id in events:
        query = urlencode({"owner_id": user["user_id"], "event_id": event_id})
        deadline = time.monotonic() + (90 if fixture.scanners else 45)
        while time.monotonic() < deadline:
            status, history = request(web + "/api/v1/deliveries?" + query, headers=key_headers)
            expect(status, 200)
            if history["items"] and history["items"][0]["status"] == "success":
                require(len(history["items"]) == 1, "Duplicate delivery intent")
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("Delivery deadline exceeded")
    status, receipt = request(callback + "/receipt")
    expect(status, 200)
    require(len(receipt["records"]) == 2, "Duplicate or missing callback")
    require(all(record["body"] == json.loads(payload) and not record["sensitive_headers"] for record in receipt["records"]), "Payload or sensitive-header contract failed")
    require(all(record["delivery_id"] for record in receipt["records"]) and len({record["delivery_id"] for record in receipt["records"]}) == 2, "Missing or duplicate delivery correlation IDs")
    expect(request(agent + "/api/v1/query", "POST", payload)[0], 422)
    scanner_proof = {}
    if fixture.scanners:
        fixture.stage = "legacy scanner automatic restart"
        scanner_proof = restart_scanners(fixture)
        scanner_proof["legacy_scanner"].update(postgres_outage_observed=True, broker_outage_observed=True,
            admission_without_redis=True, offline_hmac_denial=401, offline_api_key_denial=401,
            offline_rate_limit=429, quota_shared_between_processes=True, quota_preserved_after_redis_recovery=True)
        scanner_proof["legacy_scanner"].update(api_restart_same_container=True, quota_preserved_after_api_restart=True, api_offline_readiness=503)
        time.sleep(6)
        require(len(request(callback + "/receipt")[1]["records"]) == 2, "Scanner restart repeated delivery")
    print("PASS: bad HMAC/unsafe origin rejected; real queued signed numeric-IP delivery; sequential/concurrent duplicates and header exclusion")
    return {"upload_ready": True, "auth_denials": 4, "events": 2, "callbacks": 2,
            "concurrent_admissions": 4, "standalone_query_rejection": 422, "scanner_restarts": scanner_proof}


def verify_load(fixture, report):
    fixture.stage = "bounded isolated HTTP load"
    fixture.config()
    items = fixture.owned()
    require(all(name in items and items[name]["Id"] == fixture.items[name]["Id"] and
                items[name]["State"]["Running"] and not items[name]["State"]["OOMKilled"]
                for name in LOAD_PATHS), "Load requires original running owned APIs")
    report["profile"] = {"duration_seconds": 5, "concurrency": 4, "max_p95_ms": 500}
    report["source_sha256"] = {filename: hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest()
                               for filename in LOAD_FILES}
    report["checks"] = {}
    for name, path in LOAD_PATHS.items():
        measured = json.loads(fixture.compose("exec", "-T", name, "python", "-B", "/verification/verify_local_load.py",
                             "http://127.0.0.1:8000" + path, "--duration", "5", "--concurrency", "4"))
        report["checks"][name] = measured
        require(measured["concurrency"] == 4 and measured["expected_status"] == 200 and measured["requests"] >= 4,
                "Incomplete isolated load measurement")
        require(0 <= measured["p95_ms"] <= 500, "Isolated load p95 exceeds 500 ms")
    print("PASS: bounded owned API load; three roles, four clients, p95 <= 500 ms", flush=True)


def main(argv=None):
    require(not sys.flags.optimize, "Optimized Python is not supported")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receiver", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scanners", action="store_true", help="Verify the permanent legacy scanner with owned outages/restarts")
    parser.add_argument("--load", action="store_true", help="Probe owned APIs for 5 seconds each with 4 clients and p95 <= 500 ms")
    for kind, image in IMAGES.items():
        option = "webhook" if kind == "web" else kind
        parser.add_argument(f"--{option}-image", default=image)
    args = parser.parse_args(argv)
    if args.receiver:
        secret = os.environ.get("SMOKE_SIGNING_SECRET", "")
        require(os.environ.get("SMOKE_RECEIVER") == "1" and len(secret) >= 32, "Receiver is a fixture-only role")
        server = ThreadingHTTPServer(("0.0.0.0", 8000), receiver_handler(secret))
        signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return
    images = {kind: getattr(args, ("webhook" if kind == "web" else kind) + "_image") for kind in IMAGES}
    fixture = Fixture(images, scanners=args.scanners)
    report = {"project": fixture.project, "images": fixture.images, "external_calls_enabled": False}
    try:
        fixture.start()
        report["callback_origin"] = fixture.callback_origin
        fixture.stage = "HTTP and worker smoke"
        report["checks"] = verify(fixture)
        if args.load:
            report["load"] = {}
            verify_load(fixture, report["load"])
        report["proof"] = fixture.proof()
        report["source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["error_class"] = type(error).__name__
        report["failed_stage"] = fixture.stage
        if isinstance(error, VerificationError):
            report["failure_reason"] = str(error)
        raise
    finally:
        try:
            fixture.stop()
            report["owned_containers_stopped"] = True
        except Exception as error:
            report["passed"] = False
            report["owned_containers_stopped"] = False
            report["cleanup_error_class"] = type(error).__name__
            raise
        finally:
            artifact = fixture.directory / "receipt.json"
            artifact.write_text(json.dumps(report, indent=2))
            print("RECEIPT: " + str(artifact), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - Never expose fixture credentials in CLI failures.
        print("STOP: " + type(error).__name__ + "; details withheld", file=sys.stderr)
        raise SystemExit(1) from None
