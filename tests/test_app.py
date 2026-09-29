from io import BytesIO
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import app as app_module
import aiwebserver.database as database_module
import aiwebserver.download_scanner as download_scanner_module


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database_path = database_module.DATABASE_PATH
        database_module.DATABASE_PATH = Path(self.temp_dir.name) / "test.db"
        database_module.initialize_database()
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def tearDown(self):
        database_module.DATABASE_PATH = self.original_database_path
        self.temp_dir.cleanup()

    def test_dashboard_loads(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Security overview", response.data)
        self.assertEqual(app_module.app.config["AIWEBSERVER_HOST"], app_module.APP_HOST)
        for service_url in (
            b"http://127.0.0.1:8081/",
            b"http://127.0.0.1/nagios/",
            b"http://127.0.0.1:9090/graph",
            b"http://127.0.0.1:3000/",
            b"http://127.0.0.1:20211/",
        ):
            self.assertIn(service_url, response.data)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

    def test_untrusted_host_is_rejected(self):
        response = self.client.get("/", headers={"Host": "untrusted.example"})

        self.assertEqual(response.status_code, 400)

    def test_codespaces_forwarded_host_is_trusted(self):
        codespace_name = os.environ.get("CODESPACE_NAME")
        if not codespace_name:
            self.skipTest("Only applies inside GitHub Codespaces")

        forwarding_domain = os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
        host = f"{codespace_name}-{app_module.APP_PORT}.{forwarding_domain}"
        response = self.client.get("/", headers={"Host": host})

        self.assertEqual(response.status_code, 200)

    def test_upload_is_scanned_and_only_metadata_is_persisted(self):
        response = self.client.post(
            "/api/scan",
            data={"file": (BytesIO(b"<?php shell_exec($_GET['cmd']);"), "../payload.php")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["filename"], "payload.php")
        self.assertEqual(response.json["status"], "review")
        self.assertEqual(sorted(path.name for path in Path(self.temp_dir.name).iterdir()), ["test.db"])

    def test_status_reports_allowlist_mismatches_and_scan_totals(self):
        self.client.post(
            "/api/scan",
            data={"file": (BytesIO(b"<?php eval(base64_decode($x));"), "shell.php")},
            content_type="multipart/form-data",
        )
        listeners = [
            {"address": "127.0.0.1", "port": 8080, "process": "python", "authorized": True},
            {"address": "0.0.0.0", "port": 4444, "process": "unknown", "authorized": False},
        ]

        with patch("app.listening_ports", return_value=listeners):
            response = self.client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["scan_count"], 1)
        self.assertEqual(response.json["flagged_count"], 1)
        self.assertEqual(response.json["unauthorized_ports"], 1)
        self.assertEqual(len(response.json["scans"]), 1)

    def test_scan_requires_a_file(self):
        response = self.client.post("/api/scan")

        self.assertEqual(response.status_code, 400)

    def test_scan_downloads_finds_regular_and_archived_files(self):
        downloads = Path(self.temp_dir.name) / "downloads"
        downloads.mkdir()
        (downloads / "suspect.php").write_bytes(b"<?php shell_exec($_GET['cmd']);")
        archive_path = downloads / "source.tar.gz"
        member_data = b"<?php eval(base64_decode($payload));"
        with tarfile.open(archive_path, "w:gz") as archive:
            member = tarfile.TarInfo("nested/payload.php")
            member.size = len(member_data)
            archive.addfile(member, BytesIO(member_data))

        with patch.object(download_scanner_module, "DOWNLOADS_ROOT", downloads):
            response = self.client.post("/api/scan-downloads")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["scanned"], 2)
        self.assertEqual(response.json["review"], 2)
        status = self.client.get("/api/status").json
        names = {scan["filename"] for scan in status["scans"]}
        self.assertIn("downloads/suspect.php", names)
        self.assertIn("downloads/source.tar.gz!/nested/payload.php", names)


if __name__ == "__main__":
    unittest.main()