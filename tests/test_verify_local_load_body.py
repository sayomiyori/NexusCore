"""Bounded raw HTTP payloads, including actual chunked and compressed responses."""

import contextlib
import gzip
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import httpx

from scripts.verify_local_load import MAX_RESPONSE_BYTES, main, verify


class Body(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            self.reads += 1
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True


class LocalLoadBodyTests(unittest.TestCase):
    def test_empty_exact_limit_and_compressed_payloads_are_streamed_without_decoding(self):
        cases = (([], {}), ([b'x' * MAX_RESPONSE_BYTES], {}),
                 ([gzip.compress(b'x' * (MAX_RESPONSE_BYTES * 32))], {'Content-Encoding': 'gzip'}))
        for chunks, headers in cases:
            with self.subTest(headers=headers, chunks=len(chunks)):
                body = Body(chunks)
                response = httpx.Response(200, stream=body, headers=headers)
                client = httpx.Client(transport=httpx.MockTransport(lambda _, response=response: response))
                with patch('scripts.verify_local_load.httpx.Client', return_value=client), \
                        patch('scripts.verify_local_load.time.monotonic', side_effect=[0, 0, 0, 6, 6]), \
                        patch('scripts.verify_local_load.time.perf_counter', side_effect=[0, 0, .025, .025]), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    report = verify('http://127.0.0.1/health', 200, 5, 1)
                self.assertEqual(report['requests'], 1)
                self.assertEqual(report['p95_ms'], 25)
                self.assertEqual(json.loads(output.getvalue()), report)
                self.assertFalse(hasattr(response, '_content'))
                self.assertEqual(body.reads, len(chunks))
                self.assertTrue(body.closed and response.is_closed and client.is_closed)

    def test_oversize_or_interrupted_body_closes_everything_and_creates_no_report(self):
        cases = (([b'x' * MAX_RESPONSE_BYTES, b'x', b'must-not-read'], {}),
                 ([b'x' * MAX_RESPONSE_BYTES, b'x', b'must-not-read'], {'Content-Length': '1'}),
                 ([b'x', httpx.ReadTimeout('synthetic-private-timeout')], {}))
        for chunks, headers in cases:
            with self.subTest(headers=headers), tempfile.TemporaryDirectory() as directory:
                body = Body(chunks)
                response = httpx.Response(200, stream=body, headers=headers)
                client = httpx.Client(transport=httpx.MockTransport(lambda _, response=response: response))
                output = Path(directory) / 'report.json'
                with patch('scripts.verify_local_load.httpx.Client', return_value=client), \
                        patch('scripts.verify_local_load.time.monotonic', side_effect=[0, 0, 0]), \
                        contextlib.redirect_stdout(io.StringIO()) as stdout, \
                        contextlib.redirect_stderr(io.StringIO()) as stderr:
                    result = main(['http://127.0.0.1/health', '--concurrency', '1', '--output', str(output)])
                self.assertEqual(result, 1)
                self.assertFalse(output.exists())
                self.assertEqual(stdout.getvalue(), '')
                self.assertIn('Local HTTP probe failed', stderr.getvalue())
                self.assertNotIn('synthetic-private', stderr.getvalue())
                self.assertEqual(body.reads, 2)
                self.assertFalse(hasattr(response, '_content'))
                self.assertTrue(body.closed and response.is_closed and client.is_closed)

    def test_status_denial_closes_without_reading_body(self):
        body = Body([AssertionError('must-not-read')])
        response = httpx.Response(302, stream=body, headers={'Location': 'https://example.com/health'})
        client = httpx.Client(transport=httpx.MockTransport(lambda _: response))
        with patch('scripts.verify_local_load.httpx.Client', return_value=client), \
                patch('scripts.verify_local_load.time.monotonic', side_effect=[0, 0, 0]), \
                self.assertRaisesRegex(AssertionError, 'Unexpected local HTTP status'):
            verify('http://127.0.0.1/health', 200, 5, 1)
        self.assertEqual(body.reads, 0)
        self.assertTrue(body.closed and client.is_closed)

    def test_actual_cli_rejects_oversized_fixed_and_chunked_bodies(self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                self.send_response(200)
                if self.server.chunked:
                    self.send_header('Transfer-Encoding', 'chunked')
                else:
                    self.send_header('Content-Length', str(MAX_RESPONSE_BYTES + 1))
                self.end_headers()
                try:
                    if self.server.chunked:
                        self.wfile.write(b'10000\r\n' + b'x' * MAX_RESPONSE_BYTES + b'\r\n1\r\nx\r\n0\r\n\r\n')
                    else:
                        self.wfile.write(b'x' * (MAX_RESPONSE_BYTES + 1))
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def log_message(self, *args):
                pass

        script = Path(__file__).resolve().parents[1] / 'scripts/verify_local_load.py'
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server, tempfile.TemporaryDirectory() as directory:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for chunked in (False, True):
                    with self.subTest(chunked=chunked):
                        server.chunked = chunked
                        output = Path(directory) / f'{chunked}.json'
                        result = subprocess.run(
                            [sys.executable, str(script), f'http://127.0.0.1:{server.server_port}/health',
                             '--duration', '5', '--concurrency', '1', '--output', str(output)],
                            capture_output=True, text=True, timeout=10, check=False,
                        )
                        self.assertEqual(result.returncode, 1, result.stderr)
                        self.assertEqual(result.stdout, '')
                        self.assertIn('Local HTTP probe failed (AssertionError)', result.stderr)
                        self.assertFalse(output.exists())
            finally:
                server.shutdown()
                thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
