import os
from pathlib import Path
import sqlite3
import tarfile
import threading
from datetime import datetime, timezone

import psutil
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

from scanner import MAX_FILE_BYTES, ScanResult, scan_bytes, scan_stream


APP_PORT = int(os.environ.get("AIWEBSERVER_PORT", "8080"))
_ports_setting = os.environ.get("AIWEBSERVER_ALLOWED_PORTS", str(APP_PORT))
ALLOWED_PORTS = {
    int(value.strip())
    for value in _ports_setting.split(",")
    if value.strip().isdigit() and 1 <= int(value.strip()) <= 65535
}
DATABASE_PATH = Path(os.environ.get("AIWEBSERVER_DATABASE", "data/aiwebserver.db"))
DOWNLOADS_ROOT = Path(__file__).resolve().parent / "downloads"
DOWNLOADS_SCAN_INTERVAL = 60
MAX_ARCHIVE_MEMBERS = 10000
MAX_ARCHIVE_EXPANDED_BYTES = 512 * 1024 * 1024

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_BYTES + 1024 * 1024
app.config["AIWEBSERVER_PORT"] = APP_PORT
downloads_scan_lock = threading.Lock()


def connect_database():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with connect_database() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size INTEGER NOT NULL,
                status TEXT NOT NULL,
                findings TEXT NOT NULL,
                scanned_at TEXT NOT NULL,
                source_path TEXT,
                source_mtime_ns INTEGER
            )"""
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(scans)")}
        if "source_path" not in columns:
            connection.execute("ALTER TABLE scans ADD COLUMN source_path TEXT")
        if "source_mtime_ns" not in columns:
            connection.execute("ALTER TABLE scans ADD COLUMN source_mtime_ns INTEGER")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS scans_source_path_unique ON scans(source_path)"
        )


def recent_scans(limit=20):
    with connect_database() as connection:
        rows = connection.execute(
            "SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {
            "id": row["id"],
            "filename": row["filename"],
            "sha256": row["sha256"],
            "size": row["size"],
            "status": row["status"],
            "findings": row["findings"].split("\n") if row["findings"] else [],
            "scanned_at": row["scanned_at"],
            "source_path": row["source_path"],
        }
        for row in rows
    ]


def scan_summary():
    with connect_database() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'review' THEN 1 ELSE 0 END) AS flagged FROM scans"
        ).fetchone()
        downloads_count = connection.execute(
            "SELECT COUNT(*) FROM scans WHERE source_path IS NOT NULL"
        ).fetchone()[0]
    return {
        "total": row["total"],
        "flagged": row["flagged"] or 0,
        "downloads": downloads_count,
    }


def save_scan(result, scanned_at, source_path=None, source_mtime_ns=None):
    with connect_database() as connection:
        cursor = connection.execute(
            """INSERT INTO scans
                (filename, sha256, size, status, findings, scanned_at, source_path, source_mtime_ns)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_path) DO UPDATE SET
                filename = excluded.filename,
                sha256 = excluded.sha256,
                size = excluded.size,
                status = excluded.status,
                findings = excluded.findings,
                scanned_at = excluded.scanned_at,
                source_mtime_ns = excluded.source_mtime_ns""",
            (
                result.filename,
                result.sha256,
                result.size,
                result.status,
                "\n".join(result.findings),
                scanned_at,
                source_path,
                source_mtime_ns,
            ),
        )
        return cursor.lastrowid


def scan_downloads(force=False):
    """Scan regular files under downloads without following links or extracting archives."""
    if not DOWNLOADS_ROOT.is_dir():
        raise FileNotFoundError(f"Downloads folder not found: {DOWNLOADS_ROOT}")

    summary = {"scanned": 0, "skipped": 0, "clear": 0, "review": 0, "truncated": False}
    with downloads_scan_lock:
        for current_dir, directory_names, filenames in os.walk(DOWNLOADS_ROOT, followlinks=False):
            current_path = Path(current_dir)
            directory_names[:] = sorted(
                name for name in directory_names
                if not (current_path / name).is_symlink()
            )

            for filename in sorted(filenames):
                path = current_path / filename
                if path.is_symlink() or not path.is_file():
                    continue

                try:
                    file_stat = path.stat()
                except OSError:
                    continue

                relative_path = path.relative_to(DOWNLOADS_ROOT).as_posix()
                source_path = f"downloads/{relative_path}"
                is_tar_archive = filename.lower().endswith((".tar.gz", ".tgz", ".tar"))

                if not force and not is_tar_archive:
                    with connect_database() as connection:
                        cached = connection.execute(
                            "SELECT size, source_mtime_ns FROM scans WHERE source_path = ?",
                            (source_path,),
                        ).fetchone()
                    if cached and cached["size"] == file_stat.st_size and cached["source_mtime_ns"] == file_stat.st_mtime_ns:
                        summary["skipped"] += 1
                        continue

                if is_tar_archive:
                    member_count = 0
                    expanded_size = 0
                    try:
                        with tarfile.open(path, mode="r:*") as archive:
                            for member in archive:
                                if not member.isfile():
                                    continue
                                member_count += 1
                                expanded_size += member.size
                                member_path = Path(member.name)
                                if member_path.is_absolute() or ".." in member_path.parts:
                                    continue
                                if member_count > MAX_ARCHIVE_MEMBERS or expanded_size > MAX_ARCHIVE_EXPANDED_BYTES:
                                    summary["truncated"] = True
                                    break

                                member_stream = archive.extractfile(member)
                                if member_stream is None:
                                    continue
                                virtual_path = f"{source_path}!/{member_path.as_posix()}"
                                try:
                                    result = scan_stream(
                                        virtual_path,
                                        member_stream,
                                        flag_active_extension=False,
                                    )
                                finally:
                                    member_stream.close()
                                save_scan(result, datetime.now(timezone.utc).isoformat(), virtual_path, file_stat.st_mtime_ns)
                                summary["scanned"] += 1
                                summary[result.status] += 1
                    except (OSError, tarfile.TarError):
                        result = ScanResult(
                            filename=source_path,
                            sha256="",
                            size=file_stat.st_size,
                            status="review",
                            findings=["Could not inspect archive contents"],
                        )
                        save_scan(result, datetime.now(timezone.utc).isoformat(), source_path, file_stat.st_mtime_ns)
                        summary["scanned"] += 1
                        summary["review"] += 1
                    continue

                try:
                    with path.open("rb") as file_stream:
                        result = scan_stream(
                            source_path,
                            file_stream,
                            flag_active_extension=False,
                        )
                except OSError:
                    result = ScanResult(
                        filename=source_path,
                        sha256="",
                        size=file_stat.st_size,
                        status="review",
                        findings=["Could not read file for inspection"],
                    )
                save_scan(result, datetime.now(timezone.utc).isoformat(), source_path, file_stat.st_mtime_ns)
                summary["scanned"] += 1
                summary[result.status] += 1

    return summary


def downloads_scan_loop():
    while True:
        try:
            scan_downloads()
        except Exception:
            app.logger.exception("Automatic downloads scan failed")
        threading.Event().wait(DOWNLOADS_SCAN_INTERVAL)


def listening_ports():
    listeners = []
    try:
        connections = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError):
        connections = []

    for connection in connections:
        if connection.status != psutil.CONN_LISTEN or not connection.laddr:
            continue
        address = connection.laddr.ip if hasattr(connection.laddr, "ip") else connection.laddr[0]
        port = connection.laddr.port if hasattr(connection.laddr, "port") else connection.laddr[1]
        try:
            process_name = psutil.Process(connection.pid).name() if connection.pid else "Unknown process"
        except (psutil.Error, OSError):
            process_name = "Unknown process"
        listeners.append(
            {
                "address": address,
                "port": port,
                "process": process_name,
                "authorized": port in ALLOWED_PORTS,
            }
        )
    return sorted(listeners, key=lambda listener: (listener["port"], listener["address"]))


@app.get("/")
def dashboard():
    initialize_database()
    return render_template("index.html", allowed_ports=sorted(ALLOWED_PORTS))


@app.get("/api/status")
def status():
    ports = listening_ports()
    scans = recent_scans()
    summary = scan_summary()
    return jsonify(
        {
            "ports": ports,
            "unauthorized_ports": sum(not port["authorized"] for port in ports),
            "scans": scans,
            "scan_count": summary["total"],
            "flagged_count": summary["flagged"],
            "downloads_count": summary["downloads"],
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "allowed_ports": sorted(ALLOWED_PORTS),
        }
    )


@app.post("/api/scan")
def upload_scan():
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "Choose a file to scan."}), 400

    filename = secure_filename(uploaded.filename) or "unnamed-upload"
    data = uploaded.stream.read(MAX_FILE_BYTES + 1)
    result = scan_bytes(filename, data)
    scanned_at = datetime.now(timezone.utc).isoformat()
    scan_id = save_scan(result, scanned_at)

    response = result.as_dict()
    response.update({"id": scan_id, "scanned_at": scanned_at})
    return jsonify(response), 201


@app.post("/api/scan-downloads")
def scan_downloads_endpoint():
    initialize_database()
    try:
        summary = scan_downloads(force=True)
    except FileNotFoundError as error:
        return jsonify({"error": str(error)}), 404
    return jsonify(summary)


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({"error": "Upload is too large. The scan limit is 10 MiB."}), 413


if __name__ == "__main__":
    initialize_database()
    threading.Thread(target=downloads_scan_loop, daemon=True, name="downloads-scanner").start()
    app.run(host="127.0.0.1", port=APP_PORT, debug=False)