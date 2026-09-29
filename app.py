import threading
from datetime import datetime, timezone

import psutil
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

from aiwebserver.config import (
    ALLOWED_PORTS,
    APP_HOST,
    APP_PORT,
    MAX_FILE_BYTES,
    MAX_REQUEST_BYTES,
    TRUSTED_HOSTS,
)
from aiwebserver.database import initialize_database, recent_scans, save_scan, scan_summary
from aiwebserver.download_scanner import downloads_scan_loop, scan_downloads
from scanner import scan_bytes

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
app.config["AIWEBSERVER_PORT"] = APP_PORT
app.config["AIWEBSERVER_HOST"] = APP_HOST
app.config["TRUSTED_HOSTS"] = TRUSTED_HOSTS


@app.after_request
def add_security_headers(response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; connect-src 'self'; object-src 'none'; "
        "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


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
    threading.Thread(
        target=downloads_scan_loop,
        args=(app.logger,),
        daemon=True,
        name="downloads-scanner",
    ).start()
    app.run(host=APP_HOST, port=APP_PORT, debug=False)