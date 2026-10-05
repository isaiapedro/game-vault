"""Create a private local PostgreSQL snapshot before a collection migration."""
from datetime import datetime, timezone
import argparse
import os
from pathlib import Path
import subprocess

from dotenv import load_dotenv
from psycopg2.extensions import parse_dsn


def backup(container: str | None = None) -> Path:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / "config" / ".env")
    connection = parse_dsn(os.environ["DATABASE_URL"])
    destination = root / ".local" / "backups"
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.chmod(0o700)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot = destination / f"game-vault-{timestamp}.dump"
    environment = dict(os.environ)
    for field, variable in {
        "host": "PGHOST", "port": "PGPORT", "user": "PGUSER",
        "password": "PGPASSWORD", "dbname": "PGDATABASE",
        "sslmode": "PGSSLMODE", "options": "PGOPTIONS",
    }.items():
        if field in connection:
            environment[variable] = connection[field]
    # Do not expose the connection URI/password in process arguments or output.
    if container:
        if connection.get("host", "localhost") not in ("localhost", "127.0.0.1") or connection.get("port", "5432") != "5432":
            raise RuntimeError("Container backup requires the verified local PostgreSQL port mapping.")
        command = ["docker", "exec"]
        for variable in ("PGUSER", "PGPASSWORD", "PGDATABASE"):
            if variable in environment:
                command.extend(["--env", variable])
        command.extend([container, "pg_dump", "--host=127.0.0.1", "--format=custom", "--no-owner", "--no-acl"])
        with snapshot.open("xb") as output:
            snapshot.chmod(0o600)
            result = subprocess.run(command, env=environment, stdout=output, stderr=subprocess.PIPE)
    else:
        result = subprocess.run(
            ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--file", str(snapshot)],
            env=environment, capture_output=True,
        )
    if snapshot.exists():
        snapshot.chmod(0o600)
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        for value in sorted(connection.values(), key=len, reverse=True):
            if value:
                detail = detail.replace(value, "[redacted]")
        raise RuntimeError(f"Local database snapshot failed; migration must not proceed. {detail}")
    print(f"Snapshot saved: {snapshot.relative_to(root)}")
    return snapshot


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", help="Verified local PostgreSQL container with a matching pg_dump version")
    backup(parser.parse_args().container)
