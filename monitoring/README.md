# Workspace file-integrity monitoring

`file_integrity_exporter.py` establishes a SHA-256 baseline for regular files in this workspace and serves aggregate status at `/metrics` for Prometheus and `/nagios` for Nagios. It does not expose file names or file contents.

Start it from the workspace root with:

```bash
python3 file_integrity_exporter.py
```

The initial baseline is stored in the ignored `data/file_integrity_baseline.json`. New, changed, or deleted files remain reported until the baseline is deliberately recreated. The exporter checks metadata every 30 seconds and re-hashes unchanged files every five minutes. A file whose content changes while preserving its size and modification time is detected on the next full re-hash.

The monitor excludes `.git`, Python/Node caches and virtual environments, the root `data/` runtime directory, Prometheus and Grafana runtime data, and `.db`, `.log`, `.pyc`, SQLite sidecar, temporary, and WAL files. Symbolic links are not followed. All other regular files, including the vendored downloads and archives, are included.

Prometheus scrapes the exporter on `127.0.0.1:9110`; Grafana provisions the `Aiwebserver Prometheus` data source and `Aiwebserver File Integrity` dashboard. Copy `monitoring/nagios/aiwebserver-file-integrity.cfg` into `/opt/nagios/etc/monitor/` in the running Nagios container, validate with `nagios -v /opt/nagios/etc/nagios.cfg`, then reload Nagios. The check uses the Docker bridge gateway `172.17.0.1`.

This is a file-integrity monitor, not an antivirus verdict. Review expected changes before replacing the baseline: stop the exporter, remove `data/file_integrity_baseline.json`, and start it again. Cacti is for SNMP metric graphing and NetAlertX is for network-device discovery; neither inspects workspace file contents natively.