# Aiwebserver

Local-first web security console. The MVP accepts uploads for in-memory inspection, records scan metadata in SQLite, and compares listening ports against an explicit allowlist. It does not execute or keep uploaded files, block ports, or claim to replace antivirus software.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8080`. The dashboard refreshes port status every five seconds. Configure the expected listening ports before launch, for example:

```bash
AIWEBSERVER_ALLOWED_PORTS=8080,3306 AIWEBSERVER_PORT=8080 python app.py
```

The default allowlist contains only the dashboard port. A port marked for review is reported, not automatically closed. On Linux, the current user's permissions may limit which process names or sockets can be inspected.

## Scan behavior

The current scanner is a small, explainable set of byte-pattern checks for executable signatures, server-side script extensions, and common command-execution or obfuscation patterns. A clean result means only that these checks did not match; it is not a malware verdict. Files over 10 MiB are flagged. Upload content is held in memory for the request and discarded; only the name, size, SHA-256, findings, and timestamp are written to `data/aiwebserver.db`.

This is an MVP, not a complete XAMPP replacement: it does not bundle Apache, PHP, or MySQL. A production build should integrate maintained malware signatures (for example, ClamAV/YARA), authenticate access to the console, and run behind strict network and upload isolation before exposing it beyond localhost.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Run Cacti 1.2.31

The official Linux archive is in `downloads/`. To run it locally with Apache, MariaDB, RRDtool, and SNMP in Docker:

```bash
docker compose --env-file .env.cacti -f compose.cacti.yaml up -d --build
```

Open `http://127.0.0.1:8081`. The database and web files persist in Docker volumes. Stop the stack with `docker compose --env-file .env.cacti -f compose.cacti.yaml down`; add `-v` only if you also intend to delete its database and Cacti data.