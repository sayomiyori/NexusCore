"""Check existing exporter markers or platform denials on container loopback only."""

import argparse
import http.client
import json
import sys

MAX_BYTES = 1024 * 1024
FAMILIES = {
    "auth_service": {"auth_register_total": "counter", "active_sessions_total": "gauge"},
    "webhook_service": {"webhooks_received_total": "counter", "deliveries_total": "counter"},
    "agent_service": {"documents_total": "gauge", "chunks_total": "gauge", "llm_requests_total": "counter"},
}
DENIALS = {"webhook_service": (503, "Global metrics disabled in platform mode"),
           "agent_service": (404, "Not found")}


def verify(role: str, platform: bool = False) -> dict:
    if role not in FAMILIES or type(platform) is not bool:
        raise ValueError("Invalid metrics role/profile")
    status, detail = DENIALS[role] if platform and role in DENIALS else (200, None)
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=5)
    try:
        connection.request("GET", "/metrics")
        response = connection.getresponse()
        if response.status != status:
            raise ValueError("Unexpected metrics HTTP status")
        media_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        if media_type != ("text/plain" if status == 200 else "application/json"):
            raise ValueError("Unexpected metrics content type")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("Metrics body exceeds limit")
        if detail is not None:
            # Preserve duplicate fields so a widened denial cannot hide data.
            if json.loads(body, object_pairs_hook=list) != [("detail", detail)]:
                raise ValueError("Unexpected metrics denial body")
        else:
            lines = set(body.decode("utf-8").splitlines())
            if any(f"# TYPE {name} {kind}" not in lines for name, kind in FAMILIES[role].items()):
                raise ValueError("Required metric family marker missing")
        return {"status": status, "exported": detail is None,
                "checked_families": sorted(FAMILIES[role]) if detail is None else [], "bytes": len(body)}
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=FAMILIES)
    parser.add_argument("--platform", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = verify(args.role, args.platform)
    except (OSError, ValueError, http.client.HTTPException):
        print("Metrics probe failed; response and connection details withheld", file=sys.stderr)
        return 1
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
