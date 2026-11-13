"""Verify the Telegram/AI/reply chain through the real root Compose wiring.

The root ``docker-compose.yml`` is rendered with synthetic variables, and each
mapped service environment is overlaid onto the reviewed controlled fixture.
Only values that must differ inside an owned fixture (database/Redis/broker
URLs, synthetic secrets, fixture platform flags) are overridden; every other
root value, including pairwise key presence and model settings, is the one the
real stack would receive. The existing controlled chain then proves the three
README gaps against that environment.

No root ``.env``, no host ports, no real Telegram or Groq call.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

if __package__:
    from . import verify_stack as smoke
    from . import verify_telegram_ai as ai
else:
    import verify_stack as smoke
    import verify_telegram_ai as ai

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
PROFILES = ("telegram-ingress", "telegram-ai")

# Fixture service -> root Compose service whose environment is under test.
MAPPING = {
    "auth_service": "auth_service",
    "webhook_service": "webhook_service",
    "webhook_worker": "webhook_worker",
    "webhook_sender": "webhook_sender",
    "agent_service": "agent_service",
    "agent_worker": "agent_telegram_worker",
    "agent_publisher": "agent_reply_worker",
}

# The fixture must point at its own storage and synthetic credentials; these
# keys cannot be inherited from the rendered root stack.
OVERRIDES = {
    "DATABASE_URL",
    "REDIS_URL",
    "CELERY_BROKER_URL",
    "SECRET_KEY",
    "JWT_SECRET_KEY",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    # The fixture calls services by owned numeric IP; the root host allowlist
    # names only loopback/service names and would reject those requests.
    "TRUSTED_HOSTS",
    "PLATFORM_BOTS_ENABLED",
    "PLATFORM_TELEGRAM_ENABLED",
    "TELEGRAM_REPLIES_ENABLED",
    "TELEGRAM_AI_ENABLED",
    "PLATFORM_TENANT_ENABLED",
    "PLATFORM_READ_ENABLED",
}

REQUIRED_ENV = {
    "POSTGRES_USER": "smoke",
    "POSTGRES_PASSWORD": "smoke-db",
    "AUTH_DB_PASSWORD": "smoke-auth",
    "WEBHOOK_DB_PASSWORD": "smoke-webhook",
    "AGENT_DB_PASSWORD": "smoke-agent",
    "REDIS_PASSWORD": "smoke-redis",
    "AUTH_SECRET_KEY": "smoke-auth-secret",
    "WEBHOOK_SECRET_KEY": "smoke-webhook-secret",
    "JWT_SECRET_KEY": "smoke-jwt-secret",
}


def render_root() -> tuple[dict, str, str]:
    """Render the actual root Compose with synthetic, non-secret variables."""
    smoke.require(COMPOSE.is_file(), "Root Compose file is missing")
    with tempfile.NamedTemporaryFile(
        "w", suffix=".env", delete=False, encoding="ascii"
    ) as handle:
        path = handle.name
        for key, value in REQUIRED_ENV.items():
            handle.write(f"{key}={value}\n")
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                path,
                *[item for profile in PROFILES for item in ("--profile", profile)],
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        os.unlink(path)
    smoke.require(result.returncode == 0, "Root Compose render failed")
    rendered = json.loads(result.stdout)
    smoke.require(isinstance(rendered.get("services"), dict), "Rendered Compose is invalid")
    source = hashlib.sha256(COMPOSE.read_bytes()).hexdigest()
    return rendered, source, hashlib.sha256(result.stdout.encode()).hexdigest()


def merge_service(
    base: dict[str, object], rendered: dict[str, object]
) -> dict[str, object]:
    """Overlay the rendered root environment, keeping fixture-only values.

    A rendered empty string means the root leaves the variable unset; the
    fixture then keeps its synthetic value or placeholder. Non-empty root values
    win, except for the documented storage/secret/flag overrides.
    """
    merged = dict(base)
    for key, value in rendered.items():
        if key in OVERRIDES:
            continue
        # Rendered Compose emits JSON null for an unset variable; it must not
        # erase the fixture's synthetic value or placeholder.
        if value is None:
            continue
        if value == "" and base.get(key) not in (None, ""):
            continue
        merged[key] = value
    return merged


def derive_config(base: dict, rendered: dict) -> dict:
    """Return the controlled fixture config with root-derived service envs."""
    services = base.get("services")
    root_services = rendered.get("services")
    smoke.require(isinstance(services, dict), "Fixture config is invalid")
    smoke.require(isinstance(root_services, dict), "Rendered services are invalid")
    for fixture_name, root_name in MAPPING.items():
        smoke.require(fixture_name in services, "Fixture service is missing")
        smoke.require(root_name in root_services, "Rendered service is missing")
        services[fixture_name]["environment"] = merge_service(
            services[fixture_name].get("environment") or {},
            root_services[root_name].get("environment") or {},
        )
    return base


def assert_wiring(derived: dict, rendered: dict) -> None:
    """Fail closed when a root value silently stops reaching the fixture."""
    for fixture_name, root_name in MAPPING.items():
        root_env = (rendered["services"][root_name].get("environment") or {})
        fixture_env = derived["services"][fixture_name]["environment"]
        for key, value in root_env.items():
            if key in OVERRIDES or value is None or value == "":
                continue
            smoke.require(
                fixture_env.get(key) == value,
                f"{fixture_name}.{key} does not match the root wiring",
            )


def main(argv=None):
    smoke.require(not sys.flags.optimize, "Optimized Python is not supported")
    parser = smoke.Parser(description=__doc__)
    parser.add_argument(
        "--scanners",
        action="store_true",
        help="Verify permanent recovery loops with owned outages/restarts",
    )
    parser.add_argument(
        "--agent-revision",
        choices=smoke.AGENT_REVISIONS,
        default=smoke.AGENT_REVISIONS[0],
        help="Expected AgentHub migration head in the selected image",
    )
    for kind, image in smoke.IMAGES.items():
        parser.add_argument(
            f"--{'webhook' if kind == 'web' else kind}-image", default=image
        )
    args = parser.parse_args(argv)
    images = {
        kind: getattr(args, ("webhook" if kind == "web" else kind) + "_image")
        for kind in smoke.IMAGES
    }

    rendered, source_hash, rendered_hash = render_root()

    def factory(resolved_images: dict, scanners: bool | None = None) -> dict:
        enabled = args.scanners if scanners is None else scanners
        derived = derive_config(
            ai.ai_config(resolved_images, scanners=enabled), rendered
        )
        assert_wiring(derived, rendered)
        return derived

    fixture = smoke.Fixture(
        images,
        controlled_ai=True,
        scanners=args.scanners,
        config_factory=factory,
        agent_revision=args.agent_revision,
    )
    fixture.environment.update(
        {key: secrets.token_hex(32) for key in ("AI_SERVICE_KEY", "AI_CONTEXT_KEY", "AI_INGRESS_KEY", "AI_REPLY_KEY")},
        AI_BOT_KEY=Fernet.generate_key().decode(),
        SMOKE_CALLBACK_ORIGIN="http://127.0.0.1:8000",
    )
    report = {
        "project": fixture.project,
        "images": fixture.images,
        "external_calls_enabled": False,
        "root_compose_sha256": source_hash,
        "rendered_config_sha256": rendered_hash,
        "mapping": MAPPING,
    }
    try:
        fixture.start()
        report["callback_origin"] = fixture.callback_origin
        fixture.stage = "root-derived controlled issuer and setup"
        report["checks"] = ai.verify(fixture)
        report["metrics"] = {}
        smoke.verify_metrics(fixture, report["metrics"])
        report["proof"] = fixture.proof()
        report["gap_closures"] = {
            "bearer_accepted_on_platform_bot_routes": True,
            "telegram_secret_token_admission": "202",
            "canonical_send_observed": report["checks"]["send"] == 1,
        }
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


if __name__ == "__main__":
    main()
