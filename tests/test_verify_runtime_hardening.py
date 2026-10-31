from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / ".env.example"

API_SERVICES = {"auth_service", "webhook_service", "agent_service"}
WORKERS = {
    "webhook_worker",
    "webhook_delivery_recovery",
    "webhook_outbox_recovery",
    "agent_worker",
    "agent_telegram_worker",
    "agent_telegram_recovery",
    "agent_reply_worker",
    "agent_reply_recovery",
    "webhook_sender",
    "webhook_send_recovery",
}
SERVICES = {
    "postgres",
    "redis",
    *API_SERVICES,
    *WORKERS,
}
SERVICE_HEADER = re.compile(r"^  ([a-z0-9][a-z0-9_.-]*):$", re.MULTILINE)
DIGEST = re.compile(r"^@sha256:[0-9a-f]{64}$")
SERVICE_OVERRIDE = re.compile(
    r"^    (cap_drop|tmpfs|pids_limit|read_only):", re.MULTILINE
)
WORKER_OVERRIDE = re.compile(
    r"^    (cap_drop|tmpfs|pids_limit|read_only|security_opt):", re.MULTILINE
)


def blocks(text: str) -> dict[str, str]:
    """Split the `services:` section into per-service text blocks.

    Avoids a YAML dependency: the checks are about which anchors each service
    carries, which the file already expresses as text.
    """
    start = text.index("\nservices:\n") + len("\nservices:\n")
    section = text[start:]
    markers = list(SERVICE_HEADER.finditer(section))
    parsed: dict[str, str] = {}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(section)
        parsed[marker.group(1)] = section[marker.start() : end]
    return parsed


class RuntimeHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = COMPOSE.read_text(encoding="utf-8")
        cls.services = blocks(cls.text)

    def test_postgres_credentials_are_required(self) -> None:
        env = ENV_EXAMPLE.read_text(encoding="utf-8")
        self.assertIn("POSTGRES_USER=\n", env)
        self.assertIn("POSTGRES_PASSWORD=\n", env)
        self.assertIn("${POSTGRES_USER:?Set POSTGRES_USER}", self.text)
        self.assertIn("${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}", self.text)

    def test_shared_logging_anchor_is_bounded(self) -> None:
        anchor = self.text[self.text.index("x-default-logging:") :]
        anchor = anchor[: anchor.index("x-api-hardening:")]
        self.assertIn("driver: json-file", anchor)
        self.assertIn('max-size: "10m"', anchor)
        self.assertIn('max-file: "3"', anchor)

    def test_every_service_gets_the_shared_logging_block(self) -> None:
        self.assertEqual(set(self.services), SERVICES)
        for name, block in self.services.items():
            self.assertIn(
                "logging: *default_logging",
                block,
                f"{name} is missing the shared logging block",
            )

    def anchor(self, name: str) -> str:
        start = self.text.index(f"{name}:")
        rest = self.text[start:]
        ends = [
            index
            for index in (rest.find("\nx-", 1), rest.find("\nservices:\n"))
            if index != -1
        ]
        return rest[: min(ends)]

    def test_only_api_services_are_read_only_and_capability_free(self) -> None:
        anchor = self.anchor("x-api-hardening")
        self.assertIn("read_only: true", anchor)
        self.assertIn('cap_drop: ["ALL"]', anchor)
        self.assertIn('tmpfs: ["/tmp"]', anchor)
        self.assertIn("pids_limit: 256", anchor)
        hardened = {
            name
            for name, block in self.services.items()
            if "<<: *api_hardening" in block
        }
        self.assertEqual(hardened, API_SERVICES)
        for name in API_SERVICES:
            self.assertIn(
                'security_opt: ["no-new-privileges:true"]',
                self.services[name],
                name,
            )

    def test_workers_drop_capabilities_without_a_read_only_root(self) -> None:
        anchor = self.anchor("x-worker-hardening")
        self.assertIn('cap_drop: ["ALL"]', anchor)
        self.assertIn('tmpfs: ["/tmp"]', anchor)
        self.assertIn("pids_limit: 256", anchor)
        self.assertIn('security_opt: ["no-new-privileges:true"]', anchor)
        self.assertNotIn("read_only", anchor)
        hardened = {
            name
            for name, block in self.services.items()
            if "<<: *worker_hardening" in block
        }
        self.assertEqual(hardened, WORKERS)
        for name in WORKERS:
            self.assertNotIn("read_only", self.services[name], name)

    def test_no_service_overrides_the_shared_hardening(self) -> None:
        for name in WORKERS:
            self.assertIsNone(
                WORKER_OVERRIDE.search(self.services[name]),
                f"{name} overrides a shared hardening key",
            )
        for name in API_SERVICES:
            self.assertIsNone(
                SERVICE_OVERRIDE.search(self.services[name]),
                f"{name} overrides a shared hardening key",
            )
            self.assertIn(
                '    security_opt: ["no-new-privileges:true"]',
                self.services[name],
                name,
            )

    def test_datastores_have_no_capability_or_filedsystem_changes(self) -> None:
        for name, expected in (("postgres", "512"), ("redis", "128")):
            block = self.services[name]
            self.assertIn(f"pids_limit: {expected}", block, name)
            self.assertNotIn("read_only", block, name)
            self.assertNotIn("cap_drop", block, name)

    def test_external_images_are_pinned_by_digest(self) -> None:
        for path in (COMPOSE, ROOT / "docker-compose.telegram-demo.yml"):
            images = []
            for line in path.read_text(encoding="utf-8").splitlines():
                code = line.split("#", 1)[0].rstrip()
                if code.strip().startswith("image:"):
                    images.append(code.split("image:", 1)[1].strip())
            self.assertTrue(images, path.name)
            for image in images:
                self.assertRegex(image, r"^[^@\s]+@sha256:[0-9a-f]{64}$", f"{path.name}: {image}")


if __name__ == "__main__":
    unittest.main()
