"""Small, explainable checks for uploaded files."""

from dataclasses import asdict, dataclass
import hashlib
import re


MAX_FILE_BYTES = 10 * 1024 * 1024

SUSPICIOUS_PATTERNS = (
    ("obfuscated_eval", re.compile(rb"\beval\s*\(\s*(?:base64_decode|gzinflate|str_rot13|hex2bin)\s*\(", re.I), "Obfuscated code execution pattern"),
    ("command_execution", re.compile(rb"\b(?:shell_exec|passthru|proc_open|popen)\s*\(", re.I), "System command execution function"),
    ("dynamic_code", re.compile(rb"\bassert\s*\(\s*(?:\$_(?:GET|POST|REQUEST)|base64_decode)", re.I), "Dynamic code execution pattern"),
    ("remote_include", re.compile(rb"\b(?:include|require)(?:_once)?\s*\(?\s*['\"]https?://", re.I), "Remote code include"),
)

ACTIVE_WEB_EXTENSIONS = {".php", ".phtml", ".phar", ".cgi", ".pl", ".py", ".sh"}
EXECUTABLE_SIGNATURES = (
    (b"\x7fELF", "Linux ELF executable"),
    (b"MZ", "Windows executable signature"),
)


@dataclass(frozen=True)
class ScanResult:
    filename: str
    sha256: str
    size: int
    status: str
    findings: list[str]

    def as_dict(self):
        return asdict(self)


def scan_bytes(filename: str, data: bytes) -> ScanResult:
    """Inspect bytes without executing or extracting the uploaded content."""
    findings = []
    if len(data) > MAX_FILE_BYTES:
        findings.append("File exceeds the 10 MiB scan limit")

    lowered_name = filename.lower()
    if any(lowered_name.endswith(extension) for extension in ACTIVE_WEB_EXTENSIONS):
        findings.append("Executable or server-side script extension")

    for signature, description in EXECUTABLE_SIGNATURES:
        if data.startswith(signature):
            findings.append(description)

    sample = data[:MAX_FILE_BYTES]
    for _, pattern, description in SUSPICIOUS_PATTERNS:
        if pattern.search(sample):
            findings.append(description)

    return ScanResult(
        filename=filename,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        status="review" if findings else "clear",
        findings=findings,
    )