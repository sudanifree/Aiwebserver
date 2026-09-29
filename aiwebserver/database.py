"""SQLite setup and scan-history persistence."""

import sqlite3

from aiwebserver.config import DATABASE_PATH


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