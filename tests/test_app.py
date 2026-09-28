from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as app_module


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        app_module.DATABASE_PATH = Path(self.temp_dir.name) / "test.db"
        app_module.initialize_database()
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dashboard_loads(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Security overview", response.data)

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


if __name__ == "__main__":
    unittest.main()