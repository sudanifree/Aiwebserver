"""Small, explainable checks for uploaded files."""

from dataclasses import asdict, dataclass
import hashlib
from io import BytesIO
import re


MAX_FILE_BYTES = 10 * 1024 * 1024
SCAN_RULESET_VERSION = 2

SUSPICIOUS_PATTERNS = (
    ("obfuscated_eval", re.compile(rb"\beval\s*\(\s*(?:base64_decode|gzinflate|str_rot13|hex2bin)\s*\(", re.I), "Obfuscated code execution pattern"),
    ("command_execution", re.compile(rb"\b(?:shell_exec|passthru|proc_open|popen|system|exec)\s*\([^;]{0,200}\$_(?:GET|POST|REQUEST|COOKIE)\b", re.I), "Command execution uses request-controlled input"),
    ("dynamic_code", re.compile(rb"\bassert\s*\(\s*(?:\$_(?:GET|POST|REQUEST)|base64_decode)", re.I), "Dynamic code execution pattern"),
    ("remote_include", re.compile(rb"\b(?:include|require)(?:_once)?\s*\(?\s*['\"]https?://", re.I), "Remote code include"),
)

ACTIVE_WEB_EXTENSIONS = {".php", ".phtml", ".phar", ".cgi", ".pl", ".py", ".sh"}
EXECUTABLE_SIGNATURES = (
    (b"\x7fELF", "Linux ELF executable"),
    (b"MZ", "Windows executable signature"),
)
SCAN_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ScanResult:
    filename: str
    sha256: str
    size: int
    status: str
    findings: list[str]

    def as_dict(self):
        return asdict(self)


def _result_from_sample(
    filename: str,
    sha256: str,
    size: int,
    sample: bytes,
    flag_active_extension: bool,
) -> ScanResult:
    findings = []
    if size > MAX_FILE_BYTES:
        findings.append("File exceeds the 10 MiB scan limit")

    lowered_name = filename.lower()
    if flag_active_extension and any(lowered_name.endswith(extension) for extension in ACTIVE_WEB_EXTENSIONS):
        findings.append("Executable or server-side script extension")

    for signature, description in EXECUTABLE_SIGNATURES:
        if sample.startswith(signature):
            findings.append(description)

    for _, pattern, description in SUSPICIOUS_PATTERNS:
        if pattern.search(sample):
            findings.append(description)

    return ScanResult(
        filename=filename,
        sha256=sha256,
        size=size,
        status="review" if findings else "clear",
        findings=findings,
    )


def scan_stream(filename, stream, flag_active_extension=True) -> ScanResult:
    """Inspect a file-like stream without executing or extracting its content."""
    digest = hashlib.sha256()
    sample = bytearray()
    size = 0

    while chunk := stream.read(SCAN_CHUNK_BYTES):
        size += len(chunk)
        digest.update(chunk)
        remaining = MAX_FILE_BYTES - len(sample)
        if remaining > 0:
            sample.extend(chunk[:remaining])

    return _result_from_sample(
        filename,
        digest.hexdigest(),
        size,
        bytes(sample),
        flag_active_extension,
    )


def scan_bytes(filename: str, data: bytes) -> ScanResult:
    """Inspect bytes without executing the uploaded content."""
    return scan_stream(filename, BytesIO(data))