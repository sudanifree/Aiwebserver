import hashlib
from io import BytesIO
import unittest

from scanner import MAX_FILE_BYTES, scan_bytes, scan_stream


class ScanBytesTests(unittest.TestCase):
    def test_clean_file_is_clear_and_hashed(self):
        result = scan_bytes("notes.txt", b"hello")

        self.assertEqual(result.status, "clear")
        self.assertEqual(result.sha256, hashlib.sha256(b"hello").hexdigest())
        self.assertEqual(result.findings, [])

    def test_script_extension_and_command_execution_are_flagged(self):
        result = scan_bytes("upload.php", b"<?php shell_exec($_GET['cmd']);")

        self.assertEqual(result.status, "review")
        self.assertEqual(len(result.findings), 2)

    def test_executable_signature_is_flagged(self):
        result = scan_bytes("payload.bin", b"\x7fELFpayload")

        self.assertIn("Linux ELF executable", result.findings)

    def test_oversized_content_is_flagged_without_scanning_beyond_limit(self):
        data = b"a" * (MAX_FILE_BYTES + 1)

        result = scan_bytes("large.txt", data)

        self.assertIn("File exceeds the 10 MiB scan limit", result.findings)
        self.assertEqual(result.size, len(data))

    def test_stream_hashes_full_file_but_only_flags_extension_when_requested(self):
        data = b"safe content" * ((MAX_FILE_BYTES // 12) + 2)

        result = scan_stream("source.php", BytesIO(data), flag_active_extension=False)

        self.assertEqual(result.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(result.size, len(data))
        self.assertEqual(result.findings, ["File exceeds the 10 MiB scan limit"])


if __name__ == "__main__":
    unittest.main()