"""Health probe for the integrated AgentHub boundary.

The container must be healthy only when the API is up and the unauthenticated
legacy resources are closed. A host override that replaces the preflight command
but keeps this healthcheck therefore turns unhealthy instead of silently
serving the standalone surface.
"""

import os
import urllib.error
import urllib.request

ORIGIN = os.environ.get("AGENT_HEALTH_ORIGIN", "http://127.0.0.1:8000").rstrip("/")
CLOSED_PATHS = ("/api/v1/documents", "/metrics", "/mcp/sse")


def status(path: str) -> int | None:
    try:
        with urllib.request.urlopen(f"{ORIGIN}{path}", timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except Exception:  # noqa: BLE001 - any transport failure is unhealthy
        return None


def main() -> int:
    if status("/health") != 200:
        return 1
    if any(status(path) != 404 for path in CLOSED_PATHS):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
