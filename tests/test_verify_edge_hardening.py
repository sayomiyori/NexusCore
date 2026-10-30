from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NGINX = ROOT / "deploy" / "telegram-demo" / "default.conf.template"


class EdgeHardeningTests(unittest.TestCase):
    def test_telegram_edge_limits_by_client_not_server_name(self) -> None:
        text = NGINX.read_text(encoding="utf-8")
        self.assertIn("map $http_cf_connecting_ip $telegram_client", text)
        self.assertIn("limit_conn_zone $telegram_client", text)
        self.assertNotIn("limit_conn_zone $server_name", text)


if __name__ == "__main__":
    unittest.main()
