"""Environment-backed settings shared by the application modules."""

import os
from pathlib import Path

from scanner import MAX_FILE_BYTES


APP_PORT = int(os.environ.get("AIWEBSERVER_PORT", "8080"))
APP_HOST = os.environ.get("AIWEBSERVER_HOST", "127.0.0.1")

TRUSTED_HOSTS = ["127.0.0.1", "localhost"]
if os.environ.get("CODESPACE_NAME"):
    forwarding_domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
    TRUSTED_HOSTS.append(f"{os.environ['CODESPACE_NAME']}-{APP_PORT}.{forwarding_domain}")


def _parse_allowed_ports(value):
    ports = set()
    for item in value.split(","):
        try:
            port = int(item.strip())
        except ValueError:
            continue
        if 1 <= port <= 65535:
            ports.add(port)
    return ports


ALLOWED_PORTS = _parse_allowed_ports(os.environ.get("AIWEBSERVER_ALLOWED_PORTS", str(APP_PORT)))
DATABASE_PATH = Path(os.environ.get("AIWEBSERVER_DATABASE", "data/aiwebserver.db"))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS_ROOT = PROJECT_ROOT / "downloads"

DOWNLOADS_SCAN_INTERVAL = 60
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_FILE_BYTES + 1024 * 1024