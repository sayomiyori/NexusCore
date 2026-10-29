from __future__ import annotations

import http.server
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PREFLIGHT = SCRIPTS / "agent_platform_preflight.py"
HEALTHCHECK = SCRIPTS / "agent_platform_healthcheck.py"
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"


class AgentPlatformBoundaryTests(unittest.TestCase):
    def _run_preflight_source(self, source: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            package = base / "app" / "platform"
            package.mkdir(parents=True)
            (base / "app" / "__init__.py").write_text("", encoding="utf-8")
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "config.py").write_text(source, encoding="utf-8")
            environment = {
                **os.environ,
                "PYTHONPATH": str(base),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PLATFORM_TENANT_ENABLED": "true",
            }
            return subprocess.run(
                [sys.executable, "-B", str(PREFLIGHT)],
                cwd=base,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

    def _run_preflight(self, tenant_enabled: bool | None) -> subprocess.CompletedProcess[str]:
        source = "class Settings:\n    pass\n"
        if tenant_enabled is not None:
            source = f"class Settings:\n    tenant_enabled = {tenant_enabled!r}\n"
        source += "\n\ndef get_platform_settings():\n    return Settings()\n"
        return self._run_preflight_source(source)

    def test_preflight_fails_closed_without_tenant_support(self) -> None:
        result = self._run_preflight(None)
        self.assertEqual(result.returncode, 3)
        self.assertIn("PLATFORM_TENANT_ENABLED=true is required", result.stderr)

    def test_preflight_rejects_disabled_tenant_isolation(self) -> None:
        result = self._run_preflight(False)
        self.assertEqual(result.returncode, 3)

    def test_preflight_accepts_tenant_isolation(self) -> None:
        result = self._run_preflight(True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preflight_fails_closed_when_configuration_is_unavailable(self) -> None:
        result = self._run_preflight_source('raise RuntimeError("broken config")\n')
        self.assertEqual(result.returncode, 2)
        self.assertIn("configuration unavailable", result.stderr)

    def test_compose_requires_preflight_healthcheck_and_tenant_isolation(self) -> None:
        text = COMPOSE.read_text(encoding="utf-8")
        start = text.index("  agent_service:")
        end = text.index("  agent_worker:", start)
        service = text[start:end]
        self.assertIn(
            "PLATFORM_TENANT_ENABLED: ${PLATFORM_TENANT_ENABLED:-true}", service
        )
        self.assertIn("python /app/agent_platform_preflight.py", service)
        self.assertIn("uvicorn app.main:app", service)
        self.assertIn(
            'test: ["CMD", "python", "/app/agent_platform_healthcheck.py"]', service
        )
        self.assertIn(
            "./scripts/agent_platform_preflight.py:/app/agent_platform_preflight.py:ro",
            service,
        )
        self.assertIn(
            "./scripts/agent_platform_healthcheck.py:/app/agent_platform_healthcheck.py:ro",
            service,
        )

    def test_env_example_documents_exactly_one_secure_default(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        values = [
            line for line in text.splitlines() if line.startswith("PLATFORM_TENANT_ENABLED=")
        ]
        self.assertEqual(values, ["PLATFORM_TENANT_ENABLED=true"])

    def _run_healthcheck(self, statuses: dict[str, int]) -> subprocess.CompletedProcess[str]:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                status = statuses.get(self.path, 404)
                self.send_response(status)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            environment = {
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "AGENT_HEALTH_ORIGIN": f"http://127.0.0.1:{server.server_port}",
            }
            return subprocess.run(
                [sys.executable, "-B", str(HEALTHCHECK)],
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_healthcheck_accepts_closed_boundary(self) -> None:
        result = self._run_healthcheck(
            {
                "/health": 200,
                "/api/v1/documents": 404,
                "/metrics": 404,
                "/mcp/sse": 404,
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_healthcheck_rejects_open_legacy_route(self) -> None:
        result = self._run_healthcheck(
            {
                "/health": 200,
                "/api/v1/documents": 200,
                "/metrics": 404,
                "/mcp/sse": 404,
            }
        )
        self.assertEqual(result.returncode, 2)

    def test_healthcheck_rejects_unavailable_api(self) -> None:
        environment = {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "AGENT_HEALTH_ORIGIN": "http://127.0.0.1:1",
        }
        result = subprocess.run(
            [sys.executable, "-B", str(HEALTHCHECK)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
