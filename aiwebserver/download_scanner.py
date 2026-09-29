"""Safe scanning of regular files and archive members in downloads/."""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import tarfile
import threading

from aiwebserver import database
from aiwebserver.config import (
    DOWNLOADS_ROOT,
    DOWNLOADS_SCAN_INTERVAL,
    MAX_ARCHIVE_EXPANDED_BYTES,
    MAX_ARCHIVE_MEMBERS,
)
from scanner import ScanResult, scan_stream


_scan_lock = threading.Lock()


def _save_result(result, source_path, source_mtime_ns):
    database.save_scan(
        result,
        datetime.now(timezone.utc).isoformat(),
        source_path,
        source_mtime_ns,
    )


def _scan_archive(path, source_path, source_mtime_ns, summary):
    member_count = 0
    expanded_size = 0
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
                result = scan_stream(virtual_path, member_stream, flag_active_extension=False)
            finally:
                member_stream.close()
            _save_result(result, virtual_path, source_mtime_ns)
            summary["scanned"] += 1
            summary[result.status] += 1


def _record_archive_error(source_path, size, source_mtime_ns, summary):
    result = ScanResult(
        filename=source_path,
        sha256="",
        size=size,
        status="review",
        findings=["Could not inspect archive contents"],
    )
    _save_result(result, source_path, source_mtime_ns)
    summary["scanned"] += 1
    summary["review"] += 1


def _cached_file_is_unchanged(source_path, file_stat):
    with database.connect_database() as connection:
        cached = connection.execute(
            "SELECT size, source_mtime_ns FROM scans WHERE source_path = ?",
            (source_path,),
        ).fetchone()
    return (
        cached is not None
        and cached["size"] == file_stat.st_size
        and cached["source_mtime_ns"] == file_stat.st_mtime_ns
    )


def _scan_regular_file(path, source_path, file_stat):
    try:
        with path.open("rb") as file_stream:
            return scan_stream(source_path, file_stream, flag_active_extension=False)
    except OSError:
        return ScanResult(
            filename=source_path,
            sha256="",
            size=file_stat.st_size,
            status="review",
            findings=["Could not read file for inspection"],
        )


def scan_downloads(force=False):
    """Scan regular files without following symlinks or extracting archives."""
    if not DOWNLOADS_ROOT.is_dir():
        raise FileNotFoundError(f"Downloads folder not found: {DOWNLOADS_ROOT}")

    summary = {"scanned": 0, "skipped": 0, "clear": 0, "review": 0, "truncated": False}
    with _scan_lock:
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

                if not force and not is_tar_archive and _cached_file_is_unchanged(source_path, file_stat):
                    summary["skipped"] += 1
                    continue

                if is_tar_archive:
                    try:
                        _scan_archive(path, source_path, file_stat.st_mtime_ns, summary)
                    except (OSError, tarfile.TarError):
                        _record_archive_error(
                            source_path,
                            file_stat.st_size,
                            file_stat.st_mtime_ns,
                            summary,
                        )
                    continue

                result = _scan_regular_file(path, source_path, file_stat)
                _save_result(result, source_path, file_stat.st_mtime_ns)
                summary["scanned"] += 1
                summary[result.status] += 1

    return summary


def downloads_scan_loop(logger=None):
    logger = logger or logging.getLogger(__name__)
    while True:
        try:
            scan_downloads()
        except Exception:
            logger.exception("Automatic downloads scan failed")
        threading.Event().wait(DOWNLOADS_SCAN_INTERVAL)