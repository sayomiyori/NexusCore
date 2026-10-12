"""Bounded loopback GET probe; auth requests may append audit records."""

import argparse
import ipaddress
import json
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--expected", type=int, choices=(200, 401), default=200)
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    verify(args.url, args.expected, args.duration, args.concurrency)
