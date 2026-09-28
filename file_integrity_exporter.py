"""Expose workspace file-integrity status to Prometheus and Nagios."""

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time


WORKSPACE_ROOT = Path(__file__).resolve().parent
STATE_PATH = WORKSPACE_ROOT / "data" / "file_integrity_baseline.json"
IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
IGNORED_ROOT_DIRECTORIES = {"data"}
IGNORED_SUFFIXES = {".db", ".log", ".pyc", ".sqlite", ".sqlite3"}
HASH_CHUNK_BYTES = 1024 * 1024
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_DEEP_HASH_INTERVAL = 300


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file_stream:
        while chunk := file_stream.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


class FileIntegrityMonitor:
    def __init__(self, root=WORKSPACE_ROOT, state_path=STATE_PATH, deep_hash_interval=DEFAULT_DEEP_HASH_INTERVAL):
        self.root = Path(root).resolve()
        self.state_path = Path(state_path)
        self.deep_hash_interval = deep_hash_interval
        self._lock = threading.Lock()
        self._baseline = self._load_baseline()
        created_baseline = self._baseline is None
        if self._baseline is None:
            self._baseline, errors = self._snapshot(force_hash=True)
            if errors:
                raise OSError(f"Could not baseline {errors} workspace files")
            self._save_baseline()
        self._last_deep_hash = time.monotonic()
        if created_baseline:
            self._status = {
                "files": len(self._baseline),
                "bytes": sum(entry["size"] for entry in self._baseline.values()),
                "unchanged": len(self._baseline),
                "changed": 0,
                "added": 0,
                "deleted": 0,
                "errors": 0,
                "last_scan": time.time(),
            }
        else:
            self._status = {}
            self.refresh()

    def _load_baseline(self):
        try:
            with self.state_path.open(encoding="utf-8") as file_stream:
                baseline = json.load(file_stream)
        except FileNotFoundError:
            return None
        if not isinstance(baseline, dict) or any(
            not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str)
            for entry in baseline.values()
        ):
            raise ValueError(f"Invalid file-integrity baseline: {self.state_path}")
        return baseline

    def _save_baseline(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        with temporary_path.open("w", encoding="utf-8") as file_stream:
            json.dump(self._baseline, file_stream, separators=(",", ":"))
        os.replace(temporary_path, self.state_path)

    def _snapshot(self, force_hash=False):
        current = {}
        errors = 0
        baseline = self._baseline or {}

        def on_walk_error(_error):
            nonlocal errors
            errors += 1

        for directory, child_directories, filenames in os.walk(self.root, onerror=on_walk_error, followlinks=False):
            directory_path = Path(directory)
            relative_directory = directory_path.relative_to(self.root)
            child_directories[:] = sorted(
                name
                for name in child_directories
                if name not in IGNORED_DIRECTORIES
                and not (relative_directory == Path(".") and name in IGNORED_ROOT_DIRECTORIES)
                and not (directory_path / name).is_symlink()
            )

            for filename in filenames:
                path = directory_path / filename
                if path.is_symlink() or path.suffix.lower() in IGNORED_SUFFIXES:
                    continue
                try:
                    file_stat = path.stat()
                    if not path.is_file():
                        continue
                    relative_path = path.relative_to(self.root).as_posix()
                    previous = baseline.get(relative_path)
                    unchanged_metadata = (
                        previous is not None
                        and previous.get("size") == file_stat.st_size
                        and previous.get("mtime_ns") == file_stat.st_mtime_ns
                    )
                    if unchanged_metadata and not force_hash:
                        file_hash = previous["sha256"]
                    else:
                        file_hash = _sha256(path)
                    current[relative_path] = {
                        "size": file_stat.st_size,
                        "mtime_ns": file_stat.st_mtime_ns,
                        "sha256": file_hash,
                    }
                except OSError:
                    errors += 1

        return current, errors

    def refresh(self, force_hash=False):
        with self._lock:
            now = time.monotonic()
            if now - self._last_deep_hash >= self.deep_hash_interval:
                force_hash = True
            current, errors = self._snapshot(force_hash=force_hash)
            if force_hash:
                self._last_deep_hash = now

            baseline_paths = self._baseline.keys()
            current_paths = current.keys()
            added = current_paths - baseline_paths
            removed = baseline_paths - current_paths
            changed = {
                path
                for path in current_paths & baseline_paths
                if current[path]["sha256"] != self._baseline[path]["sha256"]
            }
            if errors:
                removed = set()

            self._status = {
                "files": len(current),
                "bytes": sum(entry["size"] for entry in current.values()),
                "unchanged": max(0, len(current) - len(added) - len(changed)),
                "changed": len(changed),
                "added": len(added),
                "deleted": len(removed),
                "errors": errors,
                "last_scan": time.time(),
            }
            return dict(self._status)

    def status(self):
        with self._lock:
            return dict(self._status)


def render_metrics(status):
    metrics = (
        ("aiwebserver_file_integrity_baseline_ready", 1),
        ("aiwebserver_file_integrity_files", status["files"]),
        ("aiwebserver_file_integrity_bytes", status["bytes"]),
        ("aiwebserver_file_integrity_unchanged_files", status["unchanged"]),
        ("aiwebserver_file_integrity_changed_files", status["changed"]),
        ("aiwebserver_file_integrity_added_files", status["added"]),
        ("aiwebserver_file_integrity_deleted_files", status["deleted"]),
        ("aiwebserver_file_integrity_scan_errors", status["errors"]),
        ("aiwebserver_file_integrity_last_scan_timestamp_seconds", status["last_scan"]),
    )
    lines = ["# HELP aiwebserver_file_integrity_files Number of files in the monitored workspace."]
    for name, value in metrics:
        lines.append(f"{name} {value}")
    return "\n".join(lines) + "\n"


def render_nagios(status):
    issue_count = status["changed"] + status["added"] + status["deleted"]
    state = "CRITICAL" if status["errors"] else "WARNING" if issue_count else "OK"
    message = (
        f"{state} - {status['files']} files; changed={status['changed']} "
        f"added={status['added']} deleted={status['deleted']} errors={status['errors']}"
    )
    performance = (
        f"files={status['files']} bytes={status['bytes']} changed={status['changed']} "
        f"added={status['added']} deleted={status['deleted']} errors={status['errors']}"
    )
    return f"{message} | {performance}\n", 503 if state != "OK" else 200


def make_handler(monitor):
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/metrics":
                body = render_metrics(monitor.status()).encode()
                status_code = 200
                content_type = "text/plain; version=0.0.4; charset=utf-8"
            elif self.path == "/nagios":
                message, status_code = render_nagios(monitor.status())
                body = message.encode()
                content_type = "text/plain; charset=utf-8"
            else:
                body = b"Not found\n"
                status_code = 404
                content_type = "text/plain; charset=utf-8"

            self.send_response(status_code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    return MetricsHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-address", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9110)
    parser.add_argument("--scan-interval", type=int, default=DEFAULT_SCAN_INTERVAL)
    parser.add_argument("--deep-hash-interval", type=int, default=DEFAULT_DEEP_HASH_INTERVAL)
    arguments = parser.parse_args()

    monitor = FileIntegrityMonitor(deep_hash_interval=arguments.deep_hash_interval)
    stop_event = threading.Event()

    def scan_loop():
        while not stop_event.wait(arguments.scan_interval):
            monitor.refresh()

    threading.Thread(target=scan_loop, daemon=True, name="file-integrity-scan").start()
    server = ThreadingHTTPServer(
        (arguments.listen_address, arguments.port),
        make_handler(monitor),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()


if __name__ == "__main__":
    main()