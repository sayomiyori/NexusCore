"""Bounded loopback GET probe; auth requests may append audit records."""

import argparse
import ipaddress
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit

import httpx

if __package__:
    from .local_files import new_descriptor
else:
    from local_files import new_descriptor


def verify(url: str, expected: int, duration: int, concurrency: int) -> dict:
    if sys.flags.optimize:
        raise ValueError('Optimized Python disables safety assertions')
    if any(not character.isprintable() or character.isspace() for character in url):
        raise ValueError("URL must not contain whitespace or control characters")
    try:
        parsed = urlsplit(url)
        safe_url = (parsed.scheme == "http" and parsed.hostname and
                    (parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback) and
                    not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and
                    parsed.path in ("/health", "/health/ready", "/api/v1/auth/me") and
                    (parsed.port is None or parsed.port > 0))
    except ValueError:
        safe_url = False
    if not safe_url:
        raise ValueError("URL must use loopback HTTP, an approved path and a valid port, without credentials or query")
    if expected not in (200, 401):
        raise ValueError("Expected status must be 200 or 401")
    if type(duration) is not int or type(concurrency) is not int or not (5 <= duration <= 60 and 1 <= concurrency <= 16):
        raise ValueError("Duration must be 5..60 seconds and concurrency 1..16, both integers")
    deadline = time.monotonic() + duration
    failed = Event()

    def run(_):
        try:
            samples = []
            with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
                while not failed.is_set() and time.monotonic() < deadline:
                    start = time.perf_counter()
                    response = client.get(url)
                    assert response.status_code == expected, "Unexpected local HTTP status"
                    samples.append((time.perf_counter() - start) * 1000)
            return samples
        except Exception:
            failed.set()
            raise

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as workers:
        samples = sorted(value for batch in workers.map(run, range(concurrency)) for value in batch)
    elapsed = time.monotonic() - started
    assert len(samples) >= concurrency
    report = {
        "requests": len(samples), "duration_seconds": round(elapsed, 2),
        "concurrency": concurrency, "expected_status": expected,
        "requests_per_second": round(len(samples) / elapsed, 2),
        "p95_ms": round(samples[math.ceil(len(samples) * .95) - 1], 2),
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
    parser.add_argument("--output", type=Path, help="Save JSON to a new file in an existing directory")
    args = parser.parse_args(argv)
    if args.max_p95_ms is not None and (not math.isfinite(args.max_p95_ms) or args.max_p95_ms <= 0):
        parser.error("--max-p95-ms must be positive and finite")
    if args.output is not None and (args.output.exists() or args.output.is_symlink() or
                                    args.output.is_junction() or not args.output.parent.is_dir()):
        parser.error("--output requires a new file in an existing directory")
    try:
        report = verify(args.url, args.expected, args.duration, args.concurrency)
    except ValueError as error:
        parser.error(str(error))
    except (httpx.HTTPError, AssertionError) as error:
        print(f"Local HTTP probe failed ({type(error).__name__}); details withheld", file=sys.stderr)
        return 1
    if args.output is not None:
        try:
            with os.fdopen(new_descriptor(args.output), "w", encoding="utf-8") as output:
                output.write(json.dumps(report) + "\n")
        except OSError:
            parser.error("Cannot create or write --output report")
    if args.max_p95_ms is not None and report["p95_ms"] > args.max_p95_ms:
        print("Reported p95 latency exceeds --max-p95-ms", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
