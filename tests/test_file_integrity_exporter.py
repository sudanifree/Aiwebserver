from pathlib import Path
import tempfile
import unittest

from file_integrity_exporter import FileIntegrityMonitor, render_metrics, render_nagios


class FileIntegrityMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "workspace"
        self.root.mkdir()
        self.state_path = Path(self.temp_dir.name) / "state.json"
        (self.root / "keep.txt").write_text("original", encoding="utf-8")
        (self.root / "gone.txt").write_text("will be removed", encoding="utf-8")
        self.monitor = FileIntegrityMonitor(self.root, self.state_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_baseline_exports_clean_status(self):
        status = self.monitor.status()

        self.assertEqual(status["files"], 2)
        self.assertEqual(status["changed"], 0)
        self.assertEqual(render_nagios(status)[1], 200)
        self.assertIn("aiwebserver_file_integrity_baseline_ready 1", render_metrics(status))

    def test_detects_changed_added_and_deleted_files(self):
        (self.root / "keep.txt").write_text("modified", encoding="utf-8")
        (self.root / "new.txt").write_text("new", encoding="utf-8")
        self.monitor.refresh(force_hash=True)
        (self.root / "gone.txt").unlink()

        status = self.monitor.refresh(force_hash=True)

        self.assertEqual(status["changed"], 1)
        self.assertEqual(status["added"], 1)
        self.assertEqual(status["deleted"], 1)
        message, http_status = render_nagios(status)
        self.assertEqual(http_status, 503)
        self.assertIn("WARNING", message)

    def test_ignores_runtime_data_and_git_directories(self):
        (self.root / "data").mkdir()
        (self.root / "data" / "runtime.db").write_text("state", encoding="utf-8")
        (self.root / ".git").mkdir()
        (self.root / ".git" / "index").write_text("index", encoding="utf-8")

        status = self.monitor.refresh(force_hash=True)

        self.assertEqual(status["files"], 2)
        self.assertEqual(status["added"], 0)


if __name__ == "__main__":
    unittest.main()