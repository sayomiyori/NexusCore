"""Isolated built-image Telegram/AI/reply verification with synthetic boundaries.

Run with the WebHook Manager virtualenv. Creates and retains fresh guarded test
databases; owns only uniquely named verification containers. No live credentials,
Telegram setup or Groq inference. Normal service startup never loads this module.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import psycopg
from cryptography.fernet import Fernet
from psycopg import sql
from sqlalchemy.engine import make_url


def create_webhook_app():
    """Override only synthetic Telegram HTTP; retain real auth and storage."""
    from src.api.main import app
    from src.api.v1.dependencies.platform import get_telegram
    from src.infrastructure.platform.clients import TelegramClient

    def boundary(request):
        assert request.url.host == "api.telegram.org"
        assert "/bot123456:synthetic_VERIFICATION-send-token/" in str(request.url)
        method = request.url.path.rsplit("/", 1)[-1]
        with httpx.Client(timeout=5, trust_env=False) as client:
            response = client.post(
                os.environ["CONTROLLED_PROVIDER_URL"] + "/controlled/" + method,
                json=json.loads(request.content) if request.content else {},
            )
        return httpx.Response(response.status_code, json=response.json())

    app.dependency_overrides[get_telegram] = lambda: TelegramClient(
        transport=httpx.MockTransport(boundary)
    )
    return app


def install_worker_boundary():
    """Actual HTTP context/admission; intercept only synthetic provider effects."""
    original = httpx.AsyncClient
    lost_receipt = False

    async def boundary(request):
        nonlocal lost_receipt
        if request.url.host == "api.groq.com":
            assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
            assert (
                request.headers["Authorization"] == "Bearer synthetic-groq-verification"
            )
            target = os.environ["CONTROLLED_PROVIDER_URL"] + "/groq"
            async with original(timeout=20, trust_env=False) as client:
                return await client.post(target, content=request.content)
        async with original(timeout=10, trust_env=False) as client:
            response = await client.send(request)
        if (
            os.environ["VERIFICATION_ROLE"] == "ingress"
            and request.url.path == "/internal/v1/telegram/updates"
            and response.status_code == 202
            and not lost_receipt
        ):
            lost_receipt = True
            return httpx.Response(503)
        return response

    class ControlledClient(original):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(boundary)
            super().__init__(**kwargs)

    httpx.AsyncClient = ControlledClient


def run(command, *, env=None, cwd=None, timeout=120):
    result = subprocess.run(
        command, env=env, cwd=cwd, capture_output=True, timeout=timeout, check=False
    )
    if result.returncode:
        raise RuntimeError(
            "Verification command failed; captured output withheld: " + command[0]
        )
    return result.stdout.decode().strip()


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for(check, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (httpx.HTTPError, psycopg.OperationalError):
            pass
        time.sleep(0.2)
    raise AssertionError("Controlled verification deadline exceeded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--webhook-image", default="webhook-task7-canonical")
    parser.add_argument("--auth-image", default="authfortress-internal-status:verification")
    parser.add_argument("--agent-image", default="agenthub-task8-check")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    tag = uuid4().hex
    url = make_url(os.environ["TEST_DATABASE_URL"])
    assert url.host in {"127.0.0.1", "localhost"} and url.database.endswith("_test")
    params = {
        "host": url.host,
        "port": url.port,
        "user": url.username,
        "password": url.password,
    }
    databases = {
        service: f"nexus_ai_{service}_{tag}_test"
        for service in ("auth", "web", "agent")
    }
    with psycopg.connect(dbname="postgres", autocommit=True, **params) as db:
        assert db.execute("SELECT current_database()").fetchone()[0] == "postgres"
        for name in databases.values():
            assert len(name) <= 63 and name.endswith(tag + "_test")
            db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    containers, files = [], []
    uploads = root / ".venv" / ("telegram-ai-uploads-" + tag)
    uploads.mkdir(parents=True)
    ports = {
        key: free_port() for key in ("auth", "web", "agent", "redis", "auth-redis")
    }
    service_key, context_key, ingress_key, reply_key = (
        secrets.token_urlsafe(32) for _ in range(4)
    )
    setup, calls = [], {"groq": 0, "send": 0}

    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/controlled/getMe":
                receipt = {
                    "ok": True,
                    "result": {
                        "id": 123456,
                        "is_bot": True,
                        "username": "controlled_bot",
                    },
                }
            elif self.path == "/controlled/setWebhook":
                setup.append(payload)
                receipt = {"ok": True, "result": True}
            elif self.path == "/groq":
                assert payload["model"] == "openai/gpt-oss-20b"
                assert (
                    payload["max_completion_tokens"] == 1024 and "tools" not in payload
                )
                assert payload["messages"][-1] == {
                    "role": "user",
                    "content": "Synthetic question",
                }
                calls["groq"] += 1
                receipt = {
                    "id": "synthetic",
                    "object": "chat.completion",
                    "created": 1,
                    "model": payload["model"],
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": "Synthetic sender answer",
                            },
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            elif self.path == "/send":
                assert payload == {"chat_id": 17, "text": "Synthetic sender answer"}
                with psycopg.connect(dbname=databases["web"], **params) as db:
                    state, marker = db.execute(
                        "SELECT state,send_started_at FROM telegram_answers"
                    ).fetchone()
                    assert state == "processing" and marker is not None
                calls["send"] += 1
                receipt = {
                    "ok": True,
                    "result": {"message_id": 717, "chat": {"id": 17}},
                }
            else:
                raise AssertionError("Unexpected controlled destination")
            data = json.dumps(receipt).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    receiver = ThreadingHTTPServer(("0.0.0.0", 0), Receiver)
    threading.Thread(target=receiver.serve_forever, daemon=True).start()
    provider = f"http://host.docker.internal:{receiver.server_address[1]}"

    def container(name, image, command, environment=None, publish=None):
        identity = "ai-verify-" + tag[:12] + "-" + name
        options = [
            "docker",
            "run",
            "-d",
            "--name",
            identity,
            "--user",
            "65534:65534",
            "--add-host",
            "auth_service:host-gateway",
            "--add-host",
            "agent_service:host-gateway",
            "--add-host",
            "webhook_service:host-gateway",
            "-v",
            str(Path(__file__).resolve()).replace("\\", "/")
            + ":/verification/verify_telegram_ai.py:ro",
        ]
        if publish:
            options += ["-p", publish]
        if image == args.agent_image:
            options += ["-v", uploads.as_posix() + ":/verification_uploads"]
        for key in environment or {}:
            options += ["-e", key]
        run(options + [image, *command], env={**os.environ, **(environment or {})})
        containers.append(identity)
        return identity

    def local_url(service, driver):
        return url.set(
            database=databases[service], drivername="postgresql+" + driver
        ).render_as_string(hide_password=False)

    def runtime_url(service, driver):
        return url.set(
            database=databases[service],
            drivername="postgresql+" + driver,
            host="host.docker.internal",
        ).render_as_string(hide_password=False)

    try:
        broker = container(
            "redis", "redis:7-alpine", [], publish=f"127.0.0.1:{ports['redis']}:6379"
        )
        container(
            "auth-redis",
            "redis:7-alpine",
            [],
            publish=f"127.0.0.1:{ports['auth-redis']}:6379",
        )
        shared = {
            "REDIS_URL": f"redis://host.docker.internal:{ports['redis']}/0",
            "CELERY_BROKER_URL": f"redis://host.docker.internal:{ports['redis']}/0",
            "SECRET_KEY": secrets.token_urlsafe(32),
            "SENTRY_DSN": "",
            "CONTROLLED_PROVIDER_URL": provider,
            "PYTHONPATH": "/verification:/app",
        }
        for service, folder, driver in (
            ("auth", "AuthFortress", "psycopg2"),
            ("web", "WebHook_Manager", "asyncpg"),
            ("agent", "AgentHub", "psycopg"),
        ):
            repo = root.parent / folder
            python = repo / ".venv/Scripts/python.exe"
            if not python.exists():
                python = repo / ".venv/bin/python"
            environment = {
                **os.environ,
                **shared,
                "DATABASE_URL": local_url(service, driver),
                "REDIS_URL": f"redis://127.0.0.1:{ports['redis']}/1",
                "JWT_SECRET_KEY": secrets.token_urlsafe(32),
                "PLATFORM_BOTS_ENABLED": "false",
                "PLATFORM_TELEGRAM_ENABLED": "false",
                "TELEGRAM_REPLIES_ENABLED": "false",
                "TELEGRAM_AI_ENABLED": "false",
            }
            run(
                [str(python), "-m", "alembic", "upgrade", "head"],
                env=environment,
                cwd=repo,
            )
            run([str(python), "-m", "alembic", "check"], env=environment, cwd=repo)
        auth_env = dict(
            shared,
            REDIS_URL=f"redis://host.docker.internal:{ports['auth-redis']}/0",
            DATABASE_URL=runtime_url("auth", "psycopg2"),
            JWT_SECRET_KEY=secrets.token_urlsafe(32),
            AUTHFORTRESS_WEBHOOK_SERVICE_KEY=service_key,
        )
        # The existing identity image has the independently verified tenant endpoint.
        container(
            "auth",
            args.auth_image,
            [
                "uvicorn",
                "app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--no-access-log",
            ],
            auth_env,
            f"127.0.0.1:{ports['auth']}:8000",
        )
        web_env = dict(
            shared,
            DATABASE_URL=runtime_url("web", "asyncpg"),
            PLATFORM_BOTS_ENABLED="true",
            PLATFORM_TELEGRAM_ENABLED="true",
            TELEGRAM_REPLIES_ENABLED="true",
            AUTHFORTRESS_BASE_URL=f"http://auth_service:{ports['auth']}",
            AUTHFORTRESS_WEBHOOK_SERVICE_KEY=service_key,
            WEBHOOK_AGENT_CONTEXT_KEY=context_key,
            WEBHOOK_AGENT_INGRESS_KEY=ingress_key,
            AGENT_WEBHOOK_REPLY_KEY=reply_key,
            BOT_CREDENTIALS_KEY=Fernet.generate_key().decode(),
            TELEGRAM_WEBHOOK_ORIGIN="https://demo.example.com",
            AGENTHUB_BASE_URL=f"http://agent_service:{ports['agent']}",
        )
        agent_env = dict(
            shared,
            REDIS_URL=f"redis://host.docker.internal:{ports['redis']}/2",
            CELERY_BROKER_URL=f"redis://host.docker.internal:{ports['redis']}/2",
            UPLOAD_DIR="/verification_uploads",
            DATABASE_URL=runtime_url("agent", "psycopg"),
            TELEGRAM_AI_ENABLED="true",
            TELEGRAM_AI_MODEL="openai/gpt-oss-20b",
            WEBHOOK_INTERNAL_URL=f"http://webhook_service:{ports['web']}",
            WEBHOOK_AGENT_SERVICE_KEY=context_key,
            WEBHOOK_AGENT_INGRESS_KEY=ingress_key,
            AGENT_WEBHOOK_REPLY_KEY=reply_key,
            GROQ_API_KEY="synthetic-groq-verification",
            OPENAI_API_KEY="",
            GEMINI_API_KEY="",
            ANTHROPIC_API_KEY="",
        )
        web_container = container(
            "web",
            args.webhook_image,
            [
                "uvicorn",
                "verify_telegram_ai:create_webhook_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--no-access-log",
            ],
            web_env,
            f"127.0.0.1:{ports['web']}:8000",
        )
        container(
            "agent",
            args.agent_image,
            [
                "uvicorn",
                "app.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                "--no-access-log",
            ],
            agent_env,
            f"127.0.0.1:{ports['agent']}:8000",
        )
        with httpx.Client(timeout=15, trust_env=False) as client:
            auth = f"http://127.0.0.1:{ports['auth']}"
            web = f"http://127.0.0.1:{ports['web']}"
            agent = f"http://127.0.0.1:{ports['agent']}"
            for base, path in (
                (auth, "/health"),
                (web, "/health/ready"),
                (agent, "/health"),
            ):
                wait_for(
                    lambda base=base, path=path: (
                        client.get(base + path).status_code == 200
                    )
                )
            account = {
                "email": f"ai-{tag}@example.com",
                "username": "verification",
                "password": "Aa1!" + secrets.token_urlsafe(24),
            }
            assert (
                client.post(auth + "/api/v1/auth/register", json=account).status_code
                == 200
            )
            login = client.post(auth + "/api/v1/auth/login", json=account)
            assert login.status_code == 200
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            tenant = client.post(
                auth + "/api/v1/tenants",
                headers=headers,
                json={"name": "AI verification"},
            )
            assert tenant.status_code == 201
            route = web + "/api/v1/tenants/" + tenant.json()["id"] + "/bots"
            bot = client.post(
                route,
                headers=headers,
                json={
                    "name": "Controlled bot",
                    "token": "123456:synthetic_VERIFICATION-send-token",
                },
            )
            assert bot.status_code == 201
            bot_route = route + "/" + bot.json()["id"]
            assert (
                client.post(
                    bot_route + "/webhook", headers=headers, json={"dry_run": True}
                ).status_code
                == 200
            )
            assert not setup
            assert (
                client.post(
                    bot_route + "/webhook", headers=headers, json={"dry_run": False}
                ).status_code
                == 200
            )
            assert len(setup) == 1
            telegram_headers = {
                "X-Telegram-Bot-Api-Secret-Token": setup[0]["secret_token"]
            }
            intake = web + "/webhooks/telegram/" + bot.json()["id"]
            payload = {
                "update_id": 42,
                "message": {
                    "message_id": 9,
                    "chat": {"id": 17, "type": "private"},
                    "text": "Synthetic question",
                },
            }
            run(["docker", "stop", broker])
            admitted = client.post(intake, headers=telegram_headers, json=payload)
            assert admitted.status_code == 202
            event_id = UUID(admitted.json()["event_id"])
            with psycopg.connect(dbname=databases["web"], **params) as db:
                assert db.execute(
                    "SELECT state,attempts FROM platform_ingress_outbox"
                ).fetchone() == ("pending", 0)
            run(["docker", "start", broker])
            commands = (
                (
                    "ingress-worker",
                    args.webhook_image,
                    dict(web_env, VERIFICATION_ROLE="ingress"),
                    [
                        "celery",
                        "-A",
                        "verify_telegram_ai:celery_app",
                        "worker",
                        "--loglevel=warning",
                        "--concurrency=1",
                        "--queues=celery",
                    ],
                ),
                (
                    "ingress-scanner",
                    args.webhook_image,
                    web_env,
                    ["python", "-m", "scripts.recover_platform_outbox"],
                ),
                (
                    "generator",
                    args.agent_image,
                    dict(agent_env, VERIFICATION_ROLE="generator"),
                    [
                        "celery",
                        "-A",
                        "verify_telegram_ai:celery_app",
                        "worker",
                        "--loglevel=warning",
                        "--concurrency=1",
                        "--queues=telegram_ai",
                    ],
                ),
                (
                    "job-scanner",
                    args.agent_image,
                    agent_env,
                    ["python", "-m", "scripts.recover_telegram_jobs"],
                ),
                (
                    "publisher",
                    args.agent_image,
                    agent_env,
                    [
                        "celery",
                        "-A",
                        "app.workers.telegram_reply_worker:celery_app",
                        "worker",
                        "--loglevel=warning",
                        "--concurrency=1",
                        "--queues=telegram_replies",
                    ],
                ),
                (
                    "reply-scanner",
                    args.agent_image,
                    agent_env,
                    ["python", "-m", "scripts.recover_telegram_replies"],
                ),
                (
                    "sender",
                    args.webhook_image,
                    dict(web_env, TELEGRAM_SEND_VERIFICATION="controlled"),
                    [
                        "celery",
                        "-A",
                        "scripts.telegram_send_verification:celery_app",
                        "worker",
                        "--loglevel=warning",
                        "--concurrency=1",
                        "--queues=telegram_send",
                    ],
                ),
                (
                    "send-scanner",
                    args.webhook_image,
                    web_env,
                    ["python", "-m", "scripts.recover_telegram_answers"],
                ),
            )
            for name, image, env, command in commands:
                container(name, image, command, env)

            def completed():
                with psycopg.connect(dbname=databases["web"], **params) as db:
                    return db.execute(
                        "SELECT state,message_id FROM telegram_answers"
                    ).fetchone() == ("succeeded", 717)

            wait_for(completed, 90)
            assert calls == {"groq": 1, "send": 1}
            assert (
                client.post(intake, headers=telegram_headers, json=payload).status_code
                == 200
            )
            changed = {**payload, "message": {**payload["message"], "text": "Changed"}}
            assert (
                client.post(intake, headers=telegram_headers, json=changed).status_code
                == 409
            )
            assert client.post(intake, content=b"invalid").status_code == 401
            with psycopg.connect(dbname=databases["web"], **params) as db:
                original = db.execute(
                    "SELECT state,attempts,published_job_id FROM platform_ingress_outbox WHERE ingress_id=%s",
                    (event_id,),
                ).fetchone()
                assert original[0:2] == ("published", 2)
                assert (
                    db.execute("SELECT count(*) FROM telegram_answers").fetchone()[0]
                    == 1
                )
            with psycopg.connect(dbname=databases["agent"], **params) as db:
                assert db.execute(
                    "SELECT id,state,answer FROM telegram_ai_jobs WHERE event_id=%s",
                    (event_id,),
                ).fetchone() == (original[2], "completed", "Synthetic sender answer")
                assert (
                    db.execute("SELECT count(*) FROM telegram_ai_usage").fetchone()[0]
                    == 1
                )
                assert (
                    db.execute("SELECT state FROM telegram_reply_outbox").fetchone()[0]
                    == "published"
                )
                for table in ("conversations", "messages", "llm_usage_records"):
                    assert (
                        db.execute(
                            sql.SQL("SELECT count(*) FROM {}").format(
                                sql.Identifier(table)
                            )
                        ).fetchone()[0]
                        == 0
                    )
            deactivated = client.post(bot_route + "/deactivate", headers=headers)
            assert deactivated.status_code == 200, (
                f"Controlled deactivate HTTP {deactivated.status_code}"
            )
            assert (
                client.post(
                    intake, headers=telegram_headers, json={"update_id": 43}
                ).status_code
                == 403
            )
            time.sleep(6)
            assert calls == {"groq": 1, "send": 1}
            container(
                "embed-worker",
                args.agent_image,
                [
                    "celery",
                    "-A",
                    "app.workers.embed_worker:celery_app",
                    "worker",
                    "--loglevel=warning",
                    "--concurrency=1",
                    "--queues=celery",
                ],
                agent_env,
            )
            # Reuse the existing standalone smoke against this isolated stack.
            # Its provisioning command targets this owned container explicitly.
            import verify_stack as legacy

            legacy.AUTH, legacy.WEBHOOK, legacy.AGENT = auth, web, agent
            original_run = subprocess.run

            def isolated_run(command, **kwargs):
                if command[:5] == [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "webhook_service",
                ]:
                    command = ["docker", "exec", "-i", web_container, *command[5:]]
                return original_run(command, **kwargs)

            with patch.object(legacy.subprocess, "run", isolated_run):
                legacy.main()
            with psycopg.connect(dbname=databases["agent"], **params) as db:
                assert (
                    db.execute("SELECT count(*) FROM telegram_ai_jobs").fetchone()[0]
                    == 1
                )
                assert (
                    db.execute("SELECT count(*) FROM telegram_ai_usage").fetchone()[0]
                    == 1
                )
            assert calls == {"groq": 1, "send": 1}
            print(
                "PASS real issuer JWT -> Telegram intake during broker outage -> replayed real admission -> bounded controlled Groq -> one result/usage -> signed answer -> canonical controlled send; duplicate/conflict/auth/deactivation and legacy isolation"
            )
        artifact = root / ".venv" / ("telegram-ai-" + tag + ".json")
        artifact.parent.mkdir(exist_ok=True)
        artifact.write_text(
            json.dumps({"databases": databases, "calls": calls}), encoding="utf-8"
        )
    finally:
        for identity in reversed(containers):
            logs = subprocess.run(
                ["docker", "logs", identity], capture_output=True, check=False
            )
            files.append(logs.stdout + logs.stderr)
            run(["docker", "stop", "--time", "5", identity])
            run(["docker", "rm", identity])
        directory = root / ".venv"
        directory.mkdir(exist_ok=True)
        (directory / ("telegram-ai-" + tag + ".log")).write_bytes(b"\n".join(files))
        receiver.shutdown()


if os.getenv("VERIFICATION_ROLE") in {"ingress", "generator"}:
    install_worker_boundary()
    if os.environ["VERIFICATION_ROLE"] == "generator":
        from app.workers import telegram_worker

        celery_app = telegram_worker.celery_app
    else:
        from src.infrastructure.queue import celery_app as worker_module

        celery_app = worker_module.celery_app
elif __name__ == "__main__":
    main()
