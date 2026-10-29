"""Fail closed when the integrated root starts AgentHub without tenant isolation.

AgentHub's standalone API is unauthenticated by design. Root Compose must run it
with ``PLATFORM_TENANT_ENABLED=true`` and a revision that implements the tenant
boundary; otherwise the untenant document/query/conversation/usage routes, MCP
and metrics remain public on the loopback port and the shared Compose network.
"""

import sys


def main() -> int:
    try:
        from app.platform.config import get_platform_settings

        settings = get_platform_settings()
    except Exception:  # noqa: BLE001 - fail closed on any import/config error
        print(
            "AgentHub tenant-isolation preflight failed: configuration unavailable",
            file=sys.stderr,
        )
        return 2

    if getattr(settings, "tenant_enabled", None) is not True:
        print(
            "AgentHub tenant-isolation preflight failed: "
            "PLATFORM_TENANT_ENABLED=true is required",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
