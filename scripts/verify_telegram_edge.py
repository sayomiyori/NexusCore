"""Exercise the real demo edge against an isolated synthetic HTTP receiver.

Requires Docker and an existing image with Python on PATH. Does not load .env,
join root networks, access databases, or contact Telegram/LLM providers.
"""

import argparse
import http.client
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BOT_ID = "00000000-0000-0000-0000-000000000001"
PATH = "/webhooks/telegram/" + BOT_ID
MARKER = "synthetic-demo-header"
RECEIVER = r'''
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
calls = 0
class Receiver(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"calls": calls}).encode())
    def do_POST(self):
        global calls
        calls += 1
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        status = 202 if self.headers.get("X-Telegram-Bot-Api-Secret-Token") == "synthetic-demo-header" else 401
        self.send_response(status)
        self.end_headers()
        self.wfile.write(json.dumps({"path": self.path, "body": body.decode(),
            "authorization": self.headers.get("Authorization"),
            "cookie": self.headers.get("Cookie"),
            "encoding": self.headers.get("Content-Encoding")}).encode())
HTTPServer(("0.0.0.0", 8000), Receiver).serve_forever()
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-image", required=True)
    args = parser.parse_args()
    project = "nexus-edge-check-" + uuid4().hex[:12]
    env = {**os.environ, "TELEGRAM_DEMO_BOT_ID": BOT_ID}
    with tempfile.TemporaryDirectory(prefix=project) as directory:
        temp = Path(directory)
        (temp / "empty.env").write_text("", encoding="utf-8")
        override = {"services": {
            "telegram_edge": {"ports": ["127.0.0.1::8080"]},
            "webhook_service": {
                "image": args.python_image,
                "entrypoint": ["python", "-u", "-c", RECEIVER],
                "networks": ["nexus_net"],
            },
        }}
        (temp / "test.json").write_text(json.dumps(override), encoding="utf-8")
        command = ["docker", "compose", "--project-name", project,
                   "--env-file", str(temp / "empty.env"),
                   "-f", str(ROOT / "docker-compose.telegram-demo.yml"),
                   "-f", str(temp / "test.json")]

        def compose(*arguments, check=True):
            result = subprocess.run(command + list(arguments), env=env,
                                    capture_output=True, text=True, timeout=180, check=False)
            if check and result.returncode:
                raise RuntimeError("Compose check failed: " + result.stderr[-2000:])
            return result

        try:
            compose("config", "--quiet")
            # Keep registry failures outside the bounded local acceptance check.
            compose("up", "-d", "--pull", "never", "--wait", "--wait-timeout", "45",
                    "webhook_service", "telegram_edge")
            port = int(compose("port", "telegram_edge", "8080").stdout.strip().rsplit(":", 1)[1])

            def request(path=PATH, method="POST", headers=None, duplicate=False):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=12)
                body = b'{"update_id":1}'
                fields = {"Content-Type": "application/json", "Content-Length": str(len(body)),
                          "X-Telegram-Bot-Api-Secret-Token": MARKER,
                          "Authorization": "Bearer synthetic", "Cookie": "synthetic=1",
                          **(headers or {})}
                try:
                    conn.putrequest(method, path)
                    for key, value in fields.items():
                        if value is not None:
                            conn.putheader(key, value)
                    if duplicate:
                        conn.putheader("X-Telegram-Bot-Api-Secret-Token", MARKER)
                    conn.endheaders(body)
                    response = conn.getresponse()
                    return response.status, response.read()
                finally:
                    conn.close()

            status, body = request(headers={"Content-Encoding": "identity"})
            assert status == 202, status
            data = json.loads(body)
            assert data == {"path": PATH, "body": '{"update_id":1}',
                            "authorization": None, "cookie": None, "encoding": "identity"}
            for path in ("/", "/docs", "/openapi.json", "/api/v1/tenants", "/internal/v1/bots",
                         PATH + "/", PATH + "?x=1", PATH.replace("telegram", "%74elegram"),
                         PATH.replace("/telegram/", "//telegram/"),
                         PATH[:-1] + "2"):
                assert request(path=path)[0] == 404, path
            for method in ("GET", "HEAD", "PUT", "DELETE", "OPTIONS"):
                assert request(method=method)[0] == 405, method
            assert request(headers={"Content-Length": "1048577"})[0] == 413
            assert request(headers={"X-Telegram-Bot-Api-Secret-Token": None})[0] == 401
            assert request(headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})[0] == 401
            assert request(duplicate=True)[0] == 401
            held = []
            try:
                for _ in range(16):
                    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
                    stream = sock.makefile("rb")
                    held.append((sock, stream))
                    sock.sendall((f"POST {PATH} HTTP/1.1\r\nHost: localhost\r\n"
                                  "Content-Length: 100\r\nExpect: 100-continue\r\n"
                                  "Content-Type: application/json\r\n\r\n").encode())
                    # 100 proves the request reached body reading and occupies a slot.
                    assert b"100 Continue" in stream.readline()
                    assert stream.readline() == b"\r\n"
                    if len(held) == 1:
                        first_ready = time.monotonic()
                assert request()[0] == 503
                status_line = held[0][1].readline()
                elapsed = time.monotonic() - first_ready
                # nginx can close an incomplete body after 100 without a final 408.
                assert status_line == b"" or status_line.split()[1:2] == [b"408"], repr(status_line)
                assert 4 <= elapsed <= 10, elapsed
            finally:
                for sock, stream in held:
                    stream.close()
                    sock.close()
            stats = compose("exec", "-T", "webhook_service", "python", "-c",
                            "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/stats').read().decode())")
            assert json.loads(stats.stdout)["calls"] == 4, stats.stdout
            for invalid in ("", "bad;return 200;", BOT_ID + "\n# injected"):
                result = compose("run", "--rm", "--no-deps", "-e", "TELEGRAM_DEMO_BOT_ID=" + invalid,
                                 "--pull", "never", "telegram_edge", "nginx", "-t", check=False)
                assert result.returncode != 0
                assert "must be a lowercase canonical UUID" in result.stderr
            logs = compose("logs", "--no-color", "telegram_edge")
            assert MARKER not in logs.stdout + logs.stderr
            # An unavailable upstream must produce a failure, never a false receipt.
            compose("stop", "webhook_service")
            assert request()[0] in (502, 504)
            print("PASS: exact route, methods, body/concurrency limits, idle timeout, header isolation,")
            print("      authentication forwarding,")
            print("      no hidden forwarding/retries, invalid configuration, safe logs, upstream outage")
        finally:
            compose("down", "--remove-orphans")


if __name__ == "__main__":
    main()
