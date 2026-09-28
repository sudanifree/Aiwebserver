import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

import psutil
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

from scanner import MAX_FILE_BYTES, scan_bytes


APP_PORT = int(os.environ.get("AIWEBSERVER_PORT", "8080"))
_ports_setting = os.environ.get("AIWEBSERVER_ALLOWED_PORTS", str(APP_PORT))
ALLOWED_PORTS = {
    int(value.strip())
    for value in _ports_setting.split(",")
    if value.strip().isdigit() and 1 <= int(value.strip()) <= 65535
}
DATABASE_PATH = Path(os.environ.get("AIWEBSERVER_DATABASE", "data/aiwebserver.db"))

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_BYTES + 1024 * 1024
app.config["AIWEBSERVER_PORT"] = APP_PORT


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
                scanned_at TEXT NOT NULL
            )"""
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
        }
        for row in rows
    ]


def scan_summary():
    with connect_database() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'review' THEN 1 ELSE 0 END) AS flagged FROM scans"
        ).fetchone()
    return {"total": row["total"], "flagged": row["flagged"] or 0}


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
    with connect_database() as connection:
        cursor = connection.execute(
            "INSERT INTO scans (filename, sha256, size, status, findings, scanned_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                result.filename,
                result.sha256,
                result.size,
                result.status,
                "\n".join(result.findings),
                scanned_at,
            ),
        )
        scan_id = cursor.lastrowid

    response = result.as_dict()
    response.update({"id": scan_id, "scanned_at": scanned_at})
    return jsonify(response), 201


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({"error": "Upload is too large. The scan limit is 10 MiB."}), 413


if __name__ == "__main__":
    initialize_database()
    app.run(host="127.0.0.1", port=APP_PORT, debug=False)