"""Bounded loopback GET probe; auth requests may append audit records."""

import argparse
import ipaddress
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx


def verify(url: str, expected: int, duration: int, concurrency: int) -> dict:
    if sys.flags.optimize:
        raise ValueError('Optimized Python disables safety assertions')
    parsed = urlsplit(url)
    assert parsed.scheme == "http" and parsed.hostname
    assert parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
    assert not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
    assert parsed.path in ("/health", "/health/ready", "/api/v1/auth/me")
    assert 5 <= duration <= 60 and 1 <= concurrency <= 16
    deadline = time.monotonic() + duration

    def run(_):
        samples = []
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
            while time.monotonic() < deadline:
                start = time.perf_counter()
                response = client.get(url)
                assert response.status_code == expected, "Unexpected local HTTP status"
                samples.append((time.perf_counter() - start) * 1000)
        return samples

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as workers:
        samples = sorted(value for batch in workers.map(run, range(concurrency)) for value in batch)
    elapsed = time.monotonic() - started
    assert len(samples) >= concurrency
    report = {
        "requests": len(samples), "duration_seconds": round(elapsed, 2),
        "concurrency": concurrency, "expected_status": expected,
        "requests_per_second": round(len(samples) / elapsed, 2),
        "p95_ms": round(samples[int((len(samples) - 1) * .95)], 2),
        "max_ms": round(samples[-1], 2),
    }
    print(json.dumps(report))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--expected", type=int, choices=(200, 401), default=200)
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--max-p95-ms", type=float, help="Fail if reported p95 latency exceeds this limit")
    args = parser.parse_args(argv)
    if args.max_p95_ms is not None and (not math.isfinite(args.max_p95_ms) or args.max_p95_ms <= 0):
        parser.error("--max-p95-ms must be positive and finite")
    report = verify(args.url, args.expected, args.duration, args.concurrency)
    if args.max_p95_ms is not None and report["p95_ms"] > args.max_p95_ms:
        print("Reported p95 latency exceeds --max-p95-ms", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
