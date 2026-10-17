"""A failed worker must stop the other workers in a disposable local probe."""

import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class LocalLoadFailFastTests(unittest.TestCase):
    def test_one_http_failure_stops_the_other_worker_before_duration(self):
        requests = []
        lock = threading.Lock()
        rendezvous = threading.Barrier(2)

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                with lock:
                    position = len(requests)
                    requests.append(self.path)
                if position < 2:
                    rendezvous.wait(timeout=5)
                self.send_response(503 if position == 0 else 200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        script = Path(__file__).resolve().parents[1] / "scripts/verify_local_load.py"
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server, \
                tempfile.TemporaryDirectory() as directory:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                destination = Path(directory) / "report.json"
                result = subprocess.run(
                    [sys.executable, str(script), f"http://127.0.0.1:{server.server_port}/health",
                     "--duration", "30", "--concurrency", "2", "--output", str(destination)],
                    capture_output=True, text=True, timeout=10, check=False,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("Local HTTP probe failed", result.stderr)
                self.assertFalse(destination.exists())
            finally:
                server.shutdown()
                thread.join(timeout=5)
        self.assertGreaterEqual(len(requests), 2)
        self.assertEqual(set(requests), {"/health"})


if __name__ == "__main__":
    unittest.main()
